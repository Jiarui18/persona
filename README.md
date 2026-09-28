# Persona onboarding demo

One conversational assistant collects an assistant name, user name, useful first task, and relevant Google-product usage through text or a browser call. During a call, the user can open Messages, type a spelling correction, and hear a spoken reply. Voice transcripts stay in backend context rather than appearing as text bubbles. The shared conversation survives hangups and mode switches. The [architecture plan](ARCHITECTURE_PLAN.md) defines the prompt-driven behavior and demo boundary.

Small monorepo: `frontend/` is Next.js on Vercel; `backend/` is FastAPI on Railway; PostgreSQL runs on Railway.

## Creator note

I vibe coded this thing with codex.
Spent around 45 mins drafting the architecture in my notes app.
Spent around 20 mins to re phrase my plan + implement ios mockup + backend.
Took a break and somehow ended up in my neighbours ferrari 458 spider (legend was kind enough to offer a ride)
Then locked in and finished in a total time of like little over 3 hrs i think

Backend targets Railway, frontend targets Vercel.

Key decisions I made (and why that makes me the best software engineer ever):

When in a call, user can still text the AI and it will respond back with voice.
So for example:

AI/voice: I've sent the name I heard in chat. Is it right?
AI/text: Jary?
Myself/text: Jiarui
AI/voice: Thanks, Jiarui. 

Thats possible because it's a:
Unified agent, there is no very split voice/text mode with own context, can withstand abuse.

Pydantic AI framework cuz it MOGS openai sdk.

## Local

The app uses PydanticAI with OpenAI for text and a direct OpenAI Realtime sideband for speech, with one shared chatbot identity, prompt set, and saved context. Postgres keeps the profile, onboarding JSON, and completed text/voice turns. The frontend has no simulator controls. There is no Google connector or task execution in this onboarding demo.

Create the local test account once (already created in this checkout):

```sh
python3 backend/create_test_account.py
```

That script prints a random password and saves only its PBKDF2 hash and a session-signing secret in `backend/.env.local` (ignored by Git). If the file exists, it refuses to replace the account. To use the existing local account, ask the project owner for its password; do not commit the local env file.

Set one key in `backend/.env.local` for both text and live calls:

```dotenv
OPENAI_API_KEY=your_direct_openai_key
```

Optionally set `TEXT_MODEL` (default `openai-responses:gpt-6-luna`), `VOICE_MODEL` (default `gpt-realtime-2.1`), and `VOICE_NAME` (default `marin`).

On this machine, Homebrew PostgreSQL is already running and `backend/.env.local` points to the local demo database, so Docker is not needed. On a fresh machine, `docker compose up -d` is an alternative; set `DATABASE_URL=postgresql://app:app@localhost:5432/app` for that container.

```sh
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --reload
```

In another terminal:

```sh
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. The Next.js `/api` route forwards requests to `BACKEND_URL` (default `http://localhost:8000`), so the test-account cookie remains first-party. The browser sends microphone audio directly to OpenAI over WebRTC; the backend sideband handles the same state tools used by PydanticAI text chat. Text typed during the call goes to the same live Realtime session and receives a spoken reply.

## Deploy

1. Deploy `frontend/` to Vercel. Set `BACKEND_URL` to the Railway backend HTTPS URL.
2. Deploy `backend/` to Railway with one worker and a Railway Postgres service. Set `DATABASE_URL`, `OPENAI_API_KEY`, `TEST_USERNAME`, `TEST_PASSWORD_HASH`, `SESSION_SECRET`, and `FRONTEND_ORIGIN` (the Vercel HTTPS origin). Do not copy the local `DATABASE_URL` to production.
3. Use a generated PBKDF2 hash and random session secret for the deployed test account. The one-off account script shows the format; keep the plaintext password outside the repo. HTTPS is required for microphone access on a non-local domain.

The gate uses one local test account, an HTTP-only signed cookie, and five failed login attempts per IP per 15 minutes in the single backend process. Restarting the process resets the in-memory attempt counter. Database schema is created at startup. The production domain and live API/WebRTC behavior still need verification after the key is configured.
