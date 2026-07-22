# Decisions (lightweight ADRs)

Each entry: the choice, why, and what would change it. Several were revised during the
build based on measurements — noted inline, because honest reversals are part of the
engineering story.

## D1 — Modular monolith, one container
One developer, two days, a live demo: every extra moving part is a failure mode on
stage. Layers are separated behind seams (repositories, provider adapters, injected
search fn) so the monolith is an architecture, not an accident. *Would change:* real
multi-tenant load → split the voice pipeline from the API.

## D2 — Hybrid workflow: deterministic FSM + LLM extraction (the deep dive)
Prompts cannot guarantee confirmation-before-action or legal transitions; frameworks
(LangGraph) add a dependency and an abstraction layer for a 6-state machine that is
~200 fully-explainable lines here. The FSM is unit-tested without any LLM. *Would
change:* N interacting workflows → a graph framework earns its keep.

## D3 — Request/response voice with streamed TTS (not WebSocket full-duplex)
Turn-based conversation doesn't need full-duplex transport, and streaming audio bugs
are the classic demo-killer. We stream where it pays: the reply text returns
immediately and TTS chunks stream to `<audio>`, cutting time-to-first-audio ~1.4 s.
Measured TTFA: 8.7 s (cold, naive) → 3.3–3.9 s (streamed + warmed + parallelized).
*Next step with a week:* LLM token streaming into sentence-chunked TTS (~2 s TTFA), or
a speech-to-speech Live API.

## D4 — SQLite on a volume, behind repositories
Single-writer app, one instance: SQLite is zero-ops and survives redeploys on the
volume (verified: a fact planted before a redeploy was there after). The repository
layer makes Postgres a connection-string change. *Would change:* >1 app instance.

## D5 — No RAG / vector DB for memory
A user accrues dozens of facts; full prompt injection costs ~200 tokens with 100%
recall. Retrieval at this scale can only *add* a miss mode — an embedding miss on
"what's my favorite color?" would fail the assignment's core scenario for negative
benefit. *Would change:* memory beyond the practical context budget, or document Q&A.

## D6 — Deterministic memory extraction sweep (revised during build)
Original design relied on the conversational model calling `save_memory`; live testing
showed it sometimes just answers (an Arabic 4-fact message saved nothing). Now a
dedicated background pass extracts facts after every turn — zero added latency,
~$0.0002/turn. In-turn saves still happen for the instant "memory updated" chip;
upserts make the overlap harmless.

## D7 — Anonymous per-browser identity (no auth)
UUID in localStorage → `X-User-Id`. Every visitor gets isolated memory with zero
sign-up friction — right for a public demo. Sessions are the seam where auth would
attach. Documented limitation: clearing browser data mints a new identity.

## D8 — Foursquare search + Geoapify geocoding (revised during build)
Foursquare's `near` geocoder failed on real usage: "New Cairo" → empty boundary,
Arabic "التجمع الخامس" → error, while the venues exist (two Sizzlers within 8 km).
Geoapify resolves districts and Arabic reliably → we search Foursquare by lat/lng +
radius. Also: `rating`/`price` response fields are premium-tier on the free plan and
draw from a near-zero quota bucket (found via live 429s) — we request default fields
only. Fallback provider selectable via `PLACES_PROVIDER`.

## D9 — Moderation as a parallel, fail-open guardrail
OpenAI's free moderation endpoint screens every input, running concurrently with the
first LLM round so its ~0.4 s disappears from the critical path; the verdict is
checked before any tool executes (side effects stay gated — tested). Fail-open on
moderation outage: for this product, availability beats blocking, and the prompt
policy + FSM guards still stand.

## D10 — stdlib logging with a request-id filter (structlog removed)
A contextvar filter gives every log line the request id — full turn correlation —
without a dependency. structlog was in the original plan; once the filter achieved the
same outcome for a single-process app, keeping the unused dependency was worse than
revising the plan.

## D11 — Container runs as root on Railway (revised during build)
The image originally ran as a non-root user (best practice); Railway mounts volumes
root-owned, and the app crashed on startup unable to create the database (verified in
deploy logs). Root-in-container is the standard trade-off on volume-backed PaaS.
Non-root would return with an entrypoint chown or a managed database.

## D12 — `create_all` + startup pruning instead of Alembic
Six tables, additive schema, two days: migration tooling is overhead without a
payoff at this scale. First schema change in production would introduce Alembic.

## D13 — Machine formats inside, human formats in the mouth
Slots store ISO dates and 24-hour times (validation, comparisons); everything spoken
converts to 12-hour ("9 PM", "الساعة 9 بالليل") because TTS reads "21:00" as
"twenty-one hundred". The boundary is explicit: FSM summaries and prompt rules convert;
tools and storage never do.
