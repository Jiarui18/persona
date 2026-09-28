import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelRequest, ModelResponse, TextPart, UserPromptPart

ROOT = Path(__file__).parent
CONFIG = json.loads((ROOT / "onboarding.json").read_text())


async def connect():
    return await psycopg.AsyncConnection.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


async def initialize():
    async with await connect() as db:
        await db.execute((ROOT / "schema.sql").read_text())


async def conversation(account_name):
    async with await connect() as db:
        row = await (await db.execute("SELECT * FROM conversations WHERE account_name=%s", (account_name,))).fetchone()
        if row:
            return row
        row_id = uuid4()
        await db.execute(
            "INSERT INTO conversations (id,account_name,profile,onboarding) VALUES (%s,%s,%s,%s) ON CONFLICT (account_name) DO NOTHING",
            (row_id, account_name, Jsonb(CONFIG["profile"]), Jsonb(CONFIG["onboarding"])),
        )
        return await (await db.execute("SELECT * FROM conversations WHERE account_name=%s", (account_name,))).fetchone()


async def state(conversation_id):
    async with await connect() as db:
        return await (await db.execute("SELECT * FROM conversations WHERE id=%s", (conversation_id,))).fetchone()


async def messages(conversation_id, visible_only=False):
    where = " AND visible AND modality='text'" if visible_only else ""
    async with await connect() as db:
        return await (await db.execute(
            "SELECT * FROM messages WHERE conversation_id=%s" + where + " ORDER BY sequence", (conversation_id,)
        )).fetchall()


async def history(conversation_id, exclude_source_key=None):
    rows = await messages(conversation_id)
    result = []
    for row in rows:
        if row["source_key"] == exclude_source_key:
            continue
        if row["model_message"] is not None:
            result.extend(ModelMessagesTypeAdapter.validate_python([row["model_message"]]))
        elif row["role"] in ("user", "assistant") and row["content"]:
            content = f"[spoken on call] {row['content']}" if row["modality"] == "voice" else row["content"]
            part = UserPromptPart(content=content) if row["role"] == "user" else TextPart(content=content)
            result.append(ModelRequest(parts=[part]) if row["role"] == "user" else ModelResponse(parts=[part]))
    return result


async def append_message(conversation_id, role, modality, content, source_key, model_message=None, call_id=None, visible=True):
    async with await connect() as db:
        async with db.transaction():
            old = await (await db.execute(
                "SELECT * FROM messages WHERE conversation_id=%s AND source_key=%s", (conversation_id, source_key)
            )).fetchone()
            if old:
                return old
            row = await (await db.execute(
                "UPDATE conversations SET next_sequence=next_sequence+1,updated_at=now() WHERE id=%s RETURNING next_sequence-1 AS sequence",
                (conversation_id,),
            )).fetchone()
            return await (await db.execute(
                "INSERT INTO messages (id,conversation_id,sequence,role,modality,content,visible,model_message,source_key,call_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (uuid4(), conversation_id, row["sequence"], role, modality, content, visible,
                 Jsonb(model_message) if model_message is not None else None, source_key, call_id),
            )).fetchone()


def project_native(message):
    role = "user" if message.__class__.__name__ == "ModelRequest" else "assistant"
    content = None
    modality = "text"
    for part in message.parts:
        if part.__class__.__name__ == "SpeechPart":
            content = getattr(part, "transcript", None)
            role = getattr(part, "speaker", role)
            modality = "voice"
            break
        if part.__class__.__name__ == "UserPromptPart" and isinstance(part.content, str):
            content = part.content
        if part.__class__.__name__ == "TextPart":
            content = part.content
    if not content:
        role = "internal"
        modality = "internal"
    return role, modality, content


def serialize_native(message, visible=True):
    payload = ModelMessagesTypeAdapter.dump_python([message], mode="json")[0]
    payload["parts"] = [part for part in payload["parts"]
                        if part.get("part_kind") not in ("system-prompt", "thinking")
                        and (visible or part.get("part_kind") != "text")]
    if payload.get("kind") == "request":
        payload["instructions"] = None
    return payload


async def save_native(conversation_id, native_messages, prefix, call_id=None, start=0, visible=True):
    for index, message in enumerate(native_messages, start):
        payload = serialize_native(message, visible=visible)
        if not payload["parts"]:
            continue
        role, modality, content = project_native(message)
        if content == "The user has just picked up the call. Greet them briefly and continue naturally from the conversation.":
            role, modality, content = "internal", "internal", None
        if call_id and role == "user" and modality == "text":
            async with await connect() as db:
                async with db.transaction():
                    row = await (await db.execute(
                        "SELECT id FROM messages WHERE conversation_id=%s AND call_id=%s AND role='user' "
                        "AND modality='text' AND content=%s AND model_message IS NULL ORDER BY sequence LIMIT 1 FOR UPDATE",
                        (conversation_id, call_id, content),
                    )).fetchone()
                    if row:
                        await db.execute("UPDATE messages SET model_message=%s WHERE id=%s", (Jsonb(payload), row["id"]))
                        continue
        source_key = f"{prefix}:{index}"
        async with await connect() as db:
            existing = await (await db.execute(
                "SELECT id FROM messages WHERE conversation_id=%s AND source_key=%s",
                (conversation_id, source_key),
            )).fetchone()
            if existing:
                await db.execute(
                    "UPDATE messages SET role=%s,modality=%s,content=%s,visible=%s,model_message=%s WHERE id=%s",
                    (role, modality, content, visible and role != "internal", Jsonb(payload), existing["id"]),
                )
                continue
        await append_message(conversation_id, role, modality, content, source_key, payload, call_id, visible and role != "internal")


async def patch(conversation_id, profile_patch, onboarding_patch, source_key):
    async with await connect() as db:
        async with db.transaction():
            receipt = await (await db.execute(
                "SELECT result FROM operations WHERE conversation_id=%s AND source_key=%s", (conversation_id, source_key)
            )).fetchone()
            if receipt:
                return receipt["result"]
            row = await (await db.execute(
                "SELECT profile,onboarding,version FROM conversations WHERE id=%s FOR UPDATE", (conversation_id,)
            )).fetchone()
            profile = dict(row["profile"])
            onboarding = dict(row["onboarding"])
            profile.update(profile_patch)
            for key, value in onboarding_patch.items():
                if key in ("Objectives", "GoogleProducts"):
                    onboarding[key] = {**onboarding[key], **value}
                else:
                    onboarding[key] = value
            if onboarding.get("HelpRequest"):
                onboarding["Objectives"]["GetTask"] = "done"
            if onboarding.get("onboarded"):
                reason = onboarding.get("CompletionReason")
                if reason == "all_resolved" and any(status == "pending" for status in onboarding["Objectives"].values()):
                    raise ValueError("all_resolved requires every objective to be resolved")
                if reason == "early_value" and not onboarding.get("HelpRequest"):
                    raise ValueError("early_value requires a task idea")
            await db.execute(
                "UPDATE conversations SET profile=%s,onboarding=%s,version=version+1,updated_at=now() WHERE id=%s",
                (Jsonb(profile), Jsonb(onboarding), conversation_id),
            )
            result = {"profile": profile, "onboarding": onboarding, "version": row["version"] + 1}
            await db.execute(
                "INSERT INTO operations (id,conversation_id,source_key,kind,result) VALUES (%s,%s,%s,'update_json',%s)",
                (uuid4(), conversation_id, source_key, Jsonb(result)),
            )
            return result


async def invitation(conversation_id):
    async with await connect() as db:
        return await (await db.execute(
            "SELECT result FROM operations WHERE conversation_id=%s AND kind='start_call' "
            "AND created_at > COALESCE((SELECT max(created_at) FROM operations WHERE conversation_id=%s AND kind='call_started'), '-infinity'::timestamptz) "
            "ORDER BY created_at DESC LIMIT 1",
            (conversation_id, conversation_id),
        )).fetchone()


async def record_call_started(conversation_id, call_id):
    async with await connect() as db:
        await db.execute(
            "INSERT INTO operations (id,conversation_id,source_key,kind,result) "
            "VALUES (%s,%s,%s,'call_started',%s) ON CONFLICT (conversation_id,source_key) DO NOTHING",
            (uuid4(), conversation_id, f"call-started:{call_id}", Jsonb({"call_id": call_id})),
        )


async def operation_result(conversation_id, source_key):
    async with await connect() as db:
        row = await (await db.execute(
            "SELECT result FROM operations WHERE conversation_id=%s AND source_key=%s",
            (conversation_id, source_key),
        )).fetchone()
        return row["result"] if row else None


async def record_operation(conversation_id, source_key, kind, result):
    async with await connect() as db:
        await db.execute(
            "INSERT INTO operations (id,conversation_id,source_key,kind,result) VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (conversation_id,source_key) DO NOTHING",
            (uuid4(), conversation_id, source_key, kind, Jsonb(result)),
        )


async def reset(conversation_id):
    async with await connect() as db:
        async with db.transaction():
            await db.execute("DELETE FROM operations WHERE conversation_id=%s", (conversation_id,))
            await db.execute("DELETE FROM messages WHERE conversation_id=%s", (conversation_id,))
            await db.execute(
                "UPDATE conversations SET profile=%s,onboarding=%s,next_sequence=1,version=version+1,updated_at=now() WHERE id=%s",
                (Jsonb(CONFIG["profile"]), Jsonb(CONFIG["onboarding"]), conversation_id),
            )
