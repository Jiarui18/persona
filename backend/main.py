import asyncio
import base64
import binascii
import hashlib
import hmac
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from uuid import UUID

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv(os.path.join(os.path.dirname(__file__), ".env.local"))
import chat
import realtime
import store
COOKIE = "persona_session"
ATTEMPTS = defaultdict(deque)
LOCKS = defaultdict(asyncio.Lock)


def credentials_ready():
    return all(os.getenv(key) for key in ("TEST_USERNAME", "TEST_PASSWORD_HASH", "SESSION_SECRET"))


def password_matches(password):
    try:
        algorithm, rounds, salt, expected = os.environ["TEST_PASSWORD_HASH"].split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, KeyError):
        return False


def sign_session(username):
    payload = f"{username}:{int(time.time()) + 7 * 86400}".encode()
    mac = hmac.new(os.environ["SESSION_SECRET"].encode(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload).decode() + "." + base64.urlsafe_b64encode(mac).decode()


def read_session(token):
    try:
        payload_b64, mac_b64 = token.split(".", 1)
        payload = base64.urlsafe_b64decode(payload_b64.encode())
        mac = base64.urlsafe_b64decode(mac_b64.encode())
        expected = hmac.new(os.environ["SESSION_SECRET"].encode(), payload, hashlib.sha256).digest()
        username, expires = payload.decode().rsplit(":", 1)
        if hmac.compare_digest(mac, expected) and int(expires) > time.time() and username == os.getenv("TEST_USERNAME"):
            return username
    except (ValueError, UnicodeDecodeError, binascii.Error):
        pass
    return None


def frontend_origin():
    return os.getenv("FRONTEND_ORIGIN", "http://localhost:3000").rstrip("/")


async def account(request: Request):
    username = read_session(request.cookies.get(COOKIE, "")) if credentials_ready() else None
    if not username:
        raise HTTPException(401, "Sign in to continue")
    return username


@asynccontextmanager
async def lifespan(_app):
    if not credentials_ready():
        raise RuntimeError("Configure TEST_USERNAME, TEST_PASSWORD_HASH and SESSION_SECRET")
    await store.initialize()
    yield
    await realtime.stop_all()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(CORSMiddleware, allow_origins=[frontend_origin()], allow_credentials=True,
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


@app.middleware("http")
async def check_origin(request, call_next):
    if request.method == "POST" and request.headers.get("origin") not in (None, frontend_origin()):
        return Response(status_code=403)
    return await call_next(request)


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=200)


class TextTurn(BaseModel):
    client_message_id: UUID
    text: str = Field(min_length=1, max_length=4000)


@app.post("/auth/login")
async def login(body: Login, request: Request, response: Response):
    ip = request.client.host if request.client else "unknown"
    attempts = ATTEMPTS[ip]
    now = time.monotonic()
    while attempts and attempts[0] < now - 900:
        attempts.popleft()
    if len(attempts) >= 5:
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
    if body.username != os.getenv("TEST_USERNAME") or not password_matches(body.password):
        attempts.append(now)
        raise HTTPException(401, "Invalid username or password")
    attempts.clear()
    response.set_cookie(COOKIE, sign_session(body.username), max_age=7 * 86400, httponly=True,
                        secure=frontend_origin().startswith("https://"),
                        samesite="none" if frontend_origin().startswith("https://") else "lax")
    return {"ok": True}


@app.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE, secure=frontend_origin().startswith("https://"),
                           samesite="none" if frontend_origin().startswith("https://") else "lax")
    return {"ok": True}


@app.get("/conversation")
async def get_conversation(username: str = Depends(account)):
    row = await store.conversation(username)
    items = await store.messages(row["id"])
    invite = await store.invitation(row["id"])
    return {
        "id": str(row["id"]), "profile": row["profile"], "onboarding": row["onboarding"],
        "messages": [{"id": str(item["id"]), "role": item["role"], "modality": item["modality"],
                      "content": item["content"], "created_at": item["created_at"].isoformat(),
                      "client_message_id": item["source_key"][5:] if item["source_key"].startswith("user:") else None}
                     for item in items if item["visible"] and item["modality"] == "text"],
        "transcript": [{"role": item["role"], "modality": item["modality"], "content": item["content"]}
                       for item in items if item["role"] in ("user", "assistant") and item["modality"] in ("text", "voice")
                       and item["content"] and (item["visible"] or item["modality"] == "voice")]
                       if row["onboarding"]["onboarded"] else [],
        "call_invitation": bool(invite and row["onboarding"]["WantsCall"]),
    }


@app.post("/conversation/open")
async def open_conversation(username: str = Depends(account)):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(503, "Set OPENAI_API_KEY on the backend to enable chat")
    row = await store.conversation(username)
    async with LOCKS[row["id"]]:
        await chat.open_conversation(row["id"])
    return await get_conversation(username)


@app.post("/conversation/reset")
async def reset_conversation(username: str = Depends(account)):
    row = await store.conversation(username)
    async with LOCKS[row["id"]]:
        for call in list(realtime.CALLS.values()):
            if call.conversation_id == row["id"]:
                await realtime.stop(call.id, row["id"])
        await store.reset(row["id"])
    return await get_conversation(username)


@app.post("/message")
async def message(body: TextTurn, username: str = Depends(account)):
    row = await store.conversation(username)
    if row["onboarding"]["onboarded"]:
        raise HTTPException(409, "Conversation ended")
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(503, "Set OPENAI_API_KEY on the backend to enable chat")
    async with LOCKS[row["id"]]:
        for call in list(realtime.CALLS.values()):
            if call.conversation_id == row["id"]:
                await realtime.stop(call.id, row["id"])
        await chat.text_turn(row["id"], body.text.strip(), str(body.client_message_id))
    return await get_conversation(username)


@app.post("/calls/offer")
async def offer(request: Request, username: str = Depends(account)):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(503, "Set OPENAI_API_KEY on the backend to enable calls")
    sdp = (await request.body()).decode("utf-8", errors="strict")
    if not sdp.strip() or len(sdp) > 100_000:
        raise HTTPException(400, "Expected an SDP offer")
    row = await store.conversation(username)
    if row["onboarding"]["onboarded"]:
        raise HTTPException(409, "Conversation ended")
    async with LOCKS[row["id"]]:
        try:
            return await realtime.start(row["id"], sdp)
        except asyncio.TimeoutError as error:
            raise HTTPException(504, "Call setup timed out") from error


@app.post("/calls/{call_id}/text")
async def call_text(call_id: str, body: TextTurn, username: str = Depends(account)):
    row = await store.conversation(username)
    if row["onboarding"]["onboarded"]:
        raise HTTPException(409, "Conversation ended")
    try:
        await realtime.send_text(call_id, row["id"], body.text.strip(), str(body.client_message_id))
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    return {"ok": True}


@app.post("/calls/{call_id}/ready")
async def call_ready(call_id: str, username: str = Depends(account)):
    row = await store.conversation(username)
    try:
        await realtime.ready(call_id, row["id"])
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    return {"ok": True}


@app.post("/calls/{call_id}/hangup")
async def hangup(call_id: str, username: str = Depends(account)):
    row = await store.conversation(username)
    async with LOCKS[row["id"]]:
        stopped = await realtime.stop(call_id, row["id"])
        if stopped and not (await store.state(row["id"]))["onboarding"]["onboarded"]:
            await chat.after_hangup(row["id"], call_id)
    return {"stopped": stopped}


@app.get("/health")
async def health():
    async with await store.connect() as db:
        await db.execute("SELECT 1")
    return {"status": "ok"}
