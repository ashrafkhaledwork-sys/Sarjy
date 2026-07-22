# Sarjy 🎙️

A bilingual (English + Egyptian Arabic) web voice assistant that **remembers you across
sessions** and **books your next dinner out** — hands-free.

**Live:** https://sarjy-production-3bc0.up.railway.app
*(append `?debug` to see live per-turn latency instrumentation)*

Tap the orb once and just talk — Sarjy detects when you finish speaking, answers out
loud, and keeps listening. It saves stable facts about you (name, preferences), sees
photos you attach, and runs a multi-step restaurant-booking workflow backed by real
restaurant data.

## The 90-second tour

> "My name is Ashraf and my favorite color is blue." → *saved silently*
> — close the tab, come back tomorrow —
> "What's my favorite color?" → **"Your favorite color is blue."**
>
> "احجزلي عشا لأربع أشخاص بكرة الساعة 8 في الزمالك، أكل إيطالي"
> → real Zamalek restaurants → "الأول" → read-back → "نعم" → **booked**
> — interrupt any time with an off-topic question; the booking survives, and so does it
> across sessions if you leave mid-way.

## Quickstart (local)

```bash
git clone https://github.com/ashrafkhaledwork-sys/Sarjy.git && cd Sarjy
cp .env.example .env       # fill in OPENAI_API_KEY (+ FOURSQUARE/GEOAPIFY keys)
docker compose up --build  # → http://localhost:8000
```

Dev mode without Docker:

```bash
python -m venv .venv
.venv/Scripts/pip install -e .[dev]        # POSIX: .venv/bin/pip
.venv/Scripts/python -m uvicorn app.main:app --reload
```

Run the tests (100 tests, no network, no API spend):

```bash
pytest
```

Verify your keys / smoke-test any deployment:

```bash
python scripts/verify_keys.py "Cairo"
python scripts/smoke_test.py https://your-deployment-url
```

## External API: Foursquare Places (+ Geoapify geocoding)

**Why this API:** a booking workflow without real data is a form-filler. Foursquare
turns Sarjy into a recommender — real venues, addresses, and malls the user recognizes
("Mori Sushi at The Waterway"). **Why this use case:** restaurant discovery + booking is
a naturally multi-step, voice-friendly task with slots, corrections, and a consequential
confirmation — ideal for demonstrating workflow orchestration.

Geoapify supplies geocoding because Foursquare's own `near` geocoder fails on Cairo
districts and Arabic names ("New Cairo" → empty boundary; "التجمع الخامس" → error). We
resolve the area to coordinates first, then search by lat/lng — each API doing what it's
best at. Provider swap is one env var (`PLACES_PROVIDER`).

**No-hallucination contract:** restaurant names enter the conversation *only* as
validated tool results — never from the model's imagination. If the search fails, Sarjy
says so. There's a test asserting the fabrication path doesn't exist.

## Architecture in one paragraph

A modular-monolith FastAPI app: one `POST /api/converse` turn loop (Whisper STT →
gpt-4o-mini with tools → streamed TTS via `GET /api/speech/{id}`), SQLite behind
repositories on a persistent volume, and the deep dive — a **deterministic booking FSM**
(`IDLE → COLLECTING → PRESENTING → CONFIRMING → COMPLETED/CANCELLED`) that owns all
workflow state. The LLM proposes tool calls; the FSM disposes: per-state tool legality,
per-field slot validation, and a confirmation guard requiring the user's literal "yes"
(نعم works too). The whole machine unit-tests with zero network. Memory is deterministic
too: a background extraction sweep persists stable facts after every turn.

Full detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ·
[docs/DECISIONS.md](docs/DECISIONS.md) · [docs/TESTING.md](docs/TESTING.md) ·
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) · [docs/DEMO.md](docs/DEMO.md) ·
[docs/LIMITATIONS.md](docs/LIMITATIONS.md)

## API surface

| Endpoint | Purpose |
|---|---|
| `POST /api/converse` | One turn: text, audio, and/or image in → reply + `audio_url` + workflow state + timings |
| `GET /api/speech/{id}` | Streams the reply's TTS audio (playback starts on first chunks) |
| `GET /api/memories` · `DELETE /api/memories[/{key}]` | The memory drawer: list, forget one, forget everything |
| `GET /api/bookings` | Booking history |
| `GET /api/metrics` | p50/p95 latency per stage, token usage, estimated cost |
| `GET /healthz` · `GET /readyz` | Liveness / DB readiness |

Interactive docs at `/docs` (FastAPI). Identity: anonymous UUID per browser via the
`X-User-Id` header — each visitor gets isolated memory with zero accounts.

## Measured performance

From `/api/metrics` over a representative mix (see docs/DEMO.md for the method):
time-to-first-audio ~3.3–3.9 s typical (was 8.7 s before streaming TTS, model tuning,
parallel moderation, and route warm-up), server processing p50 2.3 s, LLM cost
≈ $0.0004/turn. The p95 tail (~11 s) is tool-heavy booking turns on slow OpenAI draws —
discussed honestly in the presentation.

## Stack

FastAPI · SQLAlchemy + SQLite (volume-persisted) · OpenAI (gpt-4o-mini,
gpt-4o-mini-transcribe, gpt-4o-mini-tts, free moderation) · Foursquare Places +
Geoapify · vanilla-JS voice UI (VAD hands-free mode, no build step) · Docker
multi-stage · Railway · GitHub Actions CI (ruff + pytest + docker build).
