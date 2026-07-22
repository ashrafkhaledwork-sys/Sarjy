# Testing

**100 tests, ~13 s, zero network, zero API spend.** The environment is pinned before
any import (throwaway DB, fake API key, rate limits off, background sweep stubbed), so
the suite can never touch real data or credit. The same suite runs in CI on every push
(ruff → pytest → docker build).

```bash
pytest            # everything
pytest tests/unit # the FSM core, offline
```

## Where the tests are, and what they prove

| Area | Files | The claims they pin |
|---|---|---|
| **Booking FSM (the deep dive)** | `unit/test_fsm.py` | every legal transition; every guard (confirm requires CONFIRMING **and** literal user yes — English *and* Arabic with negation protection); no double-booking; per-field validation keeps good values while rejecting bad ones with reasons; corrections invalidate stale selections and re-search; resume from persisted state — all with zero LLM |
| Booking over HTTP | `integration/test_booking_flow.py` | full arc through the real API; digressions leave state untouched; resume offer across sessions; illegal tools blocked; a model that jumps the gun on confirm is stopped; mid-booking searches convert into criteria changes |
| Memory | `unit/test_memory_tools.py`, `integration/test_memory.py`, `unit/test_extraction.py` | favorite-color across sessions (and that history does *not* leak across); sensitive-data guard (cards, IDs, credentials, API keys refused); newest-wins upserts; user isolation; conversational + drawer deletes; the extraction sweep saves what the chat model forgets and survives LLM outages |
| Voice pipeline | `integration/test_converse_voice.py` | streamed-speech roundtrip; TTS failure can no longer hurt a turn; STT failures honest; size caps |
| Guardrails | `integration/test_guardrails.py` | flagged input → refusal with **no tool execution** even when the model proposed one; moderation outage fails open; injected memory values stay inside the data block; bilingual refusals |
| Restaurant search | `unit/test_places.py`, `integration/test_restaurant_search.py` | parsing; retry-then-degrade; geocoded ll+radius path; results reach the model *only* as tool data (asserted absent from the system prompt); outage → honest error marker |
| Vision | `integration/test_vision.py` | image rides the current turn as a data URL; history keeps a marker, never base64; non-images rejected |
| Reliability | `integration/test_reliability.py` | rate limit trips at exactly request 21 with the standard envelope; forget-everything; an injected crash returns a clean 500 — the exception text never leaks; `/api/metrics` aggregates |
| Infra | `unit/test_repositories.py`, `unit/test_metrics.py`, `test_health.py` | history window ordering/isolation; percentile math; health endpoints |

## Beyond the suite

- **Deployment smoke** (`scripts/smoke_test.py <url>`): health → DB → text turn →
  speech stream → real recorded voice turn → memory persistence. Exit-code gated; run
  against production after every deploy (~$0.01).
- **Failure injection** (covered in-suite): OpenAI 500/timeout at each stage,
  Foursquare 429/timeout, malformed/oversized uploads, garbage identity headers,
  crashes inside the turn loop.
- **Manual matrix** (things only hardware proves): mic capture on desktop Chrome +
  iOS Safari, VAD feel in a real room, Arabic TTS quality, mobile layout.

## Must pass before any deploy

FSM suite green · favorite-color integration test · confirmation-gate test ·
honest-failure places test · `smoke_test.py` against the target.
