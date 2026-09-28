"""Small OpenAI WebRTC sideband for published PydanticAI versions without realtime()."""
import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from urllib.parse import quote
from uuid import uuid4

import httpx
import websockets

import chat
import store

log = logging.getLogger(__name__)
CALLS = {}
TOOLS = [
    {"type": "function", "name": "update_json", "description": "Save changed facts. GoogleProducts maps names to booleans, e.g. {\"Gmail\": true}.",
     "parameters": {"type": "object", "properties": {
         "profile_patch": {"type": "object", "properties": {name: {"type": ["string", "null"]} for name in store.CONFIG["profile"]}, "additionalProperties": False},
         "onboarding_patch": {"type": "object", "properties": {
             "WantsCall": {"type": ["boolean", "null"]}, "onboarded": {"type": "boolean"},
             "CurrentObjective": {"type": ["string", "null"]}, "HelpRequest": {"type": ["string", "null"]},
             "CompletionReason": {"type": "string", "enum": store.CONFIG["completion_reasons"]},
             "GoogleProducts": {"type": "object", "additionalProperties": {"type": "boolean"}},
             "Objectives": {"type": "object", "properties": {name: {"type": "string", "enum": store.CONFIG["statuses"]} for name in store.CONFIG["objective_order"]}, "additionalProperties": False},
         }, "additionalProperties": False},
     }, "required": ["profile_patch", "onboarding_patch"]}},
    {"type": "function", "name": "send_chat_message", "description": "Post deliberate written text in the chat during this call.",
     "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"type": "function", "name": "end_onboarding", "description": "Finish after a brief closing line. all_resolved needs no pending objectives; early_value needs a saved task idea; user_requested is for a user who asks to stop.",
     "parameters": {"type": "object", "properties": {"reason": {"type": "string", "enum": store.CONFIG["completion_reasons"]}}, "required": ["reason"]}},
]


@dataclass
class Call:
    id: str
    conversation_id: object
    ws: object
    task: asyncio.Task | None = None
    ready: bool = False
    responding: bool = False
    continued: bool = False
    sent_tools: set = field(default_factory=set)


async def send(call, event):
    await call.ws.send(json.dumps(event))


async def run_tool(call, item):
    key = item.get("call_id")
    if not key or key in call.sent_tools:
        return
    call.sent_tools.add(key)
    try:
        args = json.loads(item.get("arguments") or "{}")
        if item["name"] == "update_json":
            result = await chat.save_updates(call.conversation_id, args["profile_patch"], args["onboarding_patch"], key)
            await send(call, {"type": "session.update", "session": {
                "type": "realtime", "instructions": await chat.instructions_for(call.conversation_id, True)}})
        elif item["name"] == "send_chat_message":
            result = await chat.post_chat(call.conversation_id, args["text"], key, call.id)
        elif item["name"] == "end_onboarding":
            result = await chat.finish_onboarding(call.conversation_id, args["reason"], key)
            await send(call, {"type": "session.update", "session": {
                "type": "realtime", "instructions": await chat.instructions_for(call.conversation_id, True)}})
        else:
            result = {"error": "Unknown tool"}
    except Exception as error:
        log.exception("Realtime tool failed")
        result = {"error": str(error)}
    await send(call, {"type": "conversation.item.create", "item": {
        "type": "function_call_output", "call_id": key, "output": json.dumps(result)}})
    return result


async def receive(call):
    try:
        async for raw in call.ws:
            event = json.loads(raw)
            kind = event.get("type")
            if kind == "conversation.item.input_audio_transcription.completed":
                call.continued = False
                text = event.get("transcript", "").strip()
                if text:
                    await store.append_message(call.conversation_id, "user", "voice", text,
                                               f"voice-user:{call.id}:{event['item_id']}:{event.get('content_index', 0)}", call_id=call.id, visible=False)
            elif kind == "response.output_audio_transcript.done":
                text = event.get("transcript", "").strip()
                if text:
                    await store.append_message(call.conversation_id, "assistant", "voice", text,
                                               f"voice-assistant:{call.id}:{event.get('item_id', event.get('response_id'))}:{event.get('content_index', 0)}", call_id=call.id, visible=False)
            elif kind == "response.done":
                call.responding = False
                output = event.get("response", {}).get("output", [])
                calls = [item for item in output
                         if item.get("type") == "function_call" and item.get("status", "completed") == "completed"]
                results = []
                for item in calls:
                    results.append(await run_tool(call, item))
                final = any(item.get("type") == "message" and item.get("phase") != "commentary" for item in output)
                commentary = any(item.get("type") == "message" and item.get("phase") == "commentary" for item in output)
                ended = any(item["name"] == "end_onboarding" and result and "error" not in result
                            for item, result in zip(calls, results))
                if not final and not ended and event.get("response", {}).get("status") == "completed" and (
                    calls or (commentary and not call.continued)
                ):
                    if not calls:
                        call.continued = True
                    await send(call, {"type": "response.create"})
            elif kind == "response.created":
                call.responding = True
            elif kind == "error":
                log.error("Realtime error: %s", event.get("error", {}).get("message", "unknown"))
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Realtime sideband failed")
    finally:
        CALLS.pop(call.id, None)
        await call.ws.close()


async def start(conversation_id, sdp_offer):
    active = next((call for call in CALLS.values() if call.conversation_id == conversation_id), None)
    if active:
        await stop(active.id, conversation_id)
    await store.patch(conversation_id, {}, {"WantsCall": True, "CurrentObjective": None,
                                            "Objectives": {"GetCall": "done"}},
                      f"call-pickup:{uuid4()}")
    config = {
        "type": "realtime", "model": chat.VOICE_MODEL, "output_modalities": ["audio"],
        "instructions": await chat.instructions_for(conversation_id, True),
        "audio": {"input": {"transcription": {"model": "gpt-transcribe"}},
                  "output": {"voice": os.getenv("VOICE_NAME", "marin")}},
        "tools": TOOLS, "tool_choice": "auto",
    }
    headers = {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post("https://api.openai.com/v1/realtime/calls", headers=headers,
                                     files={"sdp": (None, sdp_offer), "session": (None, json.dumps(config))})
        response.raise_for_status()
    location = response.headers.get("Location", "")
    call_id = location.rstrip("/").split("/")[-1]
    if not call_id.startswith("rtc_"):
        raise RuntimeError("Realtime response did not include a call ID")
    ws = await websockets.connect(
        f"wss://api.openai.com/v1/realtime?call_id={quote(call_id)}",
        additional_headers=headers, open_timeout=10,
    )
    call = Call(call_id, conversation_id, ws)
    CALLS[call.id] = call
    try:
        for row in await store.messages(conversation_id):
            if row["role"] not in ("user", "assistant") or not row["content"]:
                continue
            content_type = "input_text" if row["role"] == "user" else "output_text"
            await send(call, {"type": "conversation.item.create", "item": {
                "type": "message", "role": row["role"],
                "content": [{"type": content_type, "text": row["content"]}]}})
        call.task = asyncio.create_task(receive(call))
        await store.record_call_started(conversation_id, call.id)
        return {"call_id": call.id, "sdp": response.text}
    except Exception:
        CALLS.pop(call.id, None)
        await ws.close()
        raise


async def ready(call_id, conversation_id):
    call = CALLS.get(call_id)
    if call is None or call.conversation_id != conversation_id:
        raise LookupError("Call is no longer active")
    if not call.ready:
        call.ready = True
        await send(call, {"type": "response.create", "response": {
            "instructions": await chat.instructions_for(conversation_id, True)
            + "\n\nThe user has picked up the call. Greet them briefly and ask the next natural question. Do not discuss the invitation or connection."}})


async def send_text(call_id, conversation_id, content, client_id):
    call = CALLS.get(call_id)
    if call is None or call.conversation_id != conversation_id:
        raise LookupError("Call is no longer active")
    row = await store.append_message(conversation_id, "user", "text", content, f"user:{client_id}", call_id=call_id)
    if await store.operation_result(conversation_id, f"call-text:{client_id}"):
        return row
    call.continued = False
    if call.responding:
        await send(call, {"type": "response.cancel"})
        await send(call, {"type": "output_audio_buffer.clear"})
    await send(call, {"type": "conversation.item.create", "item": {
        "type": "message", "role": "user", "content": [{"type": "input_text", "text": content}]}})
    await send(call, {"type": "response.create"})
    await store.record_operation(conversation_id, f"call-text:{client_id}", "call_text_sent", {"sent": True})
    return row


async def stop(call_id, conversation_id):
    call = CALLS.get(call_id)
    if call is None or call.conversation_id != conversation_id:
        return False
    CALLS.pop(call.id, None)
    if call.task:
        call.task.cancel()
        try:
            await call.task
        except asyncio.CancelledError:
            pass
    else:
        await call.ws.close()
    return True


async def stop_all():
    for call in list(CALLS.values()):
        await stop(call.id, call.conversation_id)
