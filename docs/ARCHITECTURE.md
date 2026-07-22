# Architecture

A modular monolith: one FastAPI app, one Docker image, one database file on a
persistent volume. The simplest architecture that satisfies every requirement — each
component sits behind a seam where a heavier replacement could attach (see DECISIONS.md).

## System context

```mermaid
graph LR
    U[User - browser, mic+speaker] -->|HTTPS| S[Sarjy - FastAPI monolith on Railway]
    S -->|STT / Chat+Tools / TTS / Moderation| O[OpenAI API]
    S -->|geocoding| G[Geoapify]
    S -->|restaurant search by lat/lng| F[Foursquare Places]
    S --> DB[(SQLite on Railway volume)]
```

## Components

```mermaid
graph TB
    subgraph Browser
        UI[voice UI: VAD hands-free mic, transcript, workflow panel, memory drawer]
    end
    subgraph FastAPI app
        API[api/routes - transport, rate limits] --> ORCH[core/orchestrator - the turn loop]
        ORCH --> WF[workflow/fsm + slots - deterministic state]
        ORCH --> LLM[services/llm - chat + tools]
        ORCH --> MOD[services/moderation - parallel guardrail]
        ORCH --> EXT[core/extraction - background memory sweep]
        API --> STT[services/stt] 
        API --> TTS[services/tts - streamed]
        ORCH --> TOOLS[tools/registry - legality gate + dispatch]
        TOOLS --> PL[tools/places - Foursquare/Geoapify adapter]
        WF --> REPO[db/repositories]
        ORCH --> REPO
        REPO --> SQL[(SQLite)]
    end
    UI -->|POST /api/converse| API
    UI -->|GET /api/speech/id| TTS
```

**Layer responsibilities**

| Layer | Owns | Never does |
|---|---|---|
| `api/` | HTTP transport, validation, rate limits, metrics rows | business logic |
| `core/orchestrator` | the turn loop: context → LLM ⇄ tools → reply | workflow state decisions |
| `workflow/` | FSM states, transitions, guards, slot validation | LLM calls, HTTP (search fn injected) |
| `tools/` | the LLM↔world boundary: specs, legality gate, dispatch | trusting model arguments (Pydantic-validated) |
| `services/` | thin provider adapters (OpenAI, moderation) | retaining state |
| `db/` | persistence behind repositories | leaking SQLAlchemy upward |

## One voice turn

```mermaid
sequenceDiagram
    participant B as Browser
    participant A as FastAPI
    participant O as OpenAI
    participant P as Places
    B->>A: POST /api/converse (audio)
    A->>O: transcribe (STT)
    par moderation runs concurrently with the first LLM round
        A->>O: moderation(user text)
    and
        A->>A: load memories + workflow state + history
        A->>O: chat.completions (tools)
    end
    Note over A: verdict checked BEFORE any tool executes
    opt tool rounds (max 4)
        O-->>A: update_booking / select_option / confirm / save_memory / search
        A->>A: FSM validates, transitions, persists
        A->>P: geocode + search (FSM-triggered)
        A->>O: tool results → next round / final reply
    end
    A-->>B: JSON: transcript, reply, audio_url, workflow, timings
    B->>A: GET /api/speech/id
    A-->>B: TTS audio streamed - playback starts on first chunks
    Note over A: background: memory extraction sweep (zero added latency)
```

## The deep dive: the booking FSM

```mermaid
stateDiagram-v2
    [*] --> IDLE
    IDLE --> COLLECTING: booking intent
    COLLECTING --> COLLECTING: slot filled / invalid re-ask / digression
    COLLECTING --> PRESENTING: required slots complete → auto-search
    PRESENTING --> PRESENTING: criteria change → re-search
    PRESENTING --> CONFIRMING: select_option
    CONFIRMING --> PRESENTING: criteria change (selection cleared)
    CONFIRMING --> COMPLETED: explicit yes (EN or AR) → persisted
    COLLECTING --> CANCELLED: cancel
    PRESENTING --> CANCELLED: cancel
    CONFIRMING --> CANCELLED: cancel
```

**The LLM proposes; the FSM disposes.** Four deterministic guarantees no prompt can
provide:

1. **Tool legality per state** — `confirm_booking` outside `CONFIRMING` is rejected
   before any logic runs; a mid-booking `search_restaurants` call is transparently
   converted into a criteria update + re-search.
2. **Per-field slot validation** — "party of 250 tomorrow at 8" keeps the valid date
   and time, rejects the party size *with a reason* the model relays.
3. **The confirmation double-guard** — booking requires state `CONFIRMING` **and** a
   literal affirmation in the user's own words this turn (`yes`, `نعم`, `تمام`…, with
   negation protection). A prompt injection or model hallucination cannot book.
4. **Persistence every turn** — state survives sessions; a returning user gets a
   resume offer with slots intact.

The FSM takes its search function by injection, so all 30+ workflow tests run with
zero network and zero LLM.

## Memory

Distinct lifecycles, distinct tables — never one blob:

| Store | Scope | Retention |
|---|---|---|
| `messages` (chat context) | per session | 30 days |
| `memories` (stable facts) | per user, cross-session | until user deletes (drawer / "forget X" / forget-all) |
| `bookings` (workflow state) | per user, cross-session | permanent record |
| `turn_metrics` (observability) | global | 30 days |

Facts are captured twice over: the conversational model can call `save_memory`
in-turn, and a **background extraction sweep** (a dedicated LLM pass after every reply,
off the critical path) guarantees capture even when the model just answers. Upserts
make the redundancy harmless. Recall is injection, not retrieval: every fact rides the
system prompt (~200 tokens at realistic scale), so the favorite-color question can
never miss. A server-side guard refuses card-number/ID/credential-shaped values even
if the model tries to save them.

## Trust boundaries & failure paths

- Browser→server: all input validated (UUID identity header, size caps on audio/image,
  Pydantic everywhere). LLM output rendered with `textContent`, never `innerHTML`.
- Server→OpenAI/Foursquare: tool *outputs* are data, never instructions — delimited in
  the prompt, tested with injection strings; the FSM is the structural backstop.
- Every external hop: timeout + bounded retries + a distinct graceful degradation
  (STT fails → typed fallback offered; TTS fails → browser voice; search fails →
  honest "unavailable"; LLM fails → apologetic 503 envelope; moderation outage →
  fail-open). Every error is the standard envelope with a request id — a catch-all
  handler guarantees no stack trace ever leaves the server.
