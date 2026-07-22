# Sarjy — 5-minute technical presentation

Hard stop at **4:30** (30 s safety). Slide 6 is designed droppable if the demo runs
long. Rehearse ×3 with a timer; the demo script lives in ../DEMO.md.

---

## Slide 1 — The problem (0:00–0:25)

**Visual:** product shot + one line: *"Voice assistants forget you, and can't finish a task."*

Say: "Two failures define most voice assistants: no memory between conversations, and
no ability to carry a multi-step task to completion. Sarjy is my answer to both — a
bilingual voice assistant that remembers you across sessions and books your dinner,
hands-free. It's live; let me show you."

## Slide 2 — Live demo (0:25–1:55)

**Visual:** the app, `?debug` on. Follow DEMO.md: memory save → booking with digression
+ correction → confirm → second browser: cross-session recall + resume offer.

While it thinks: "the panel you see is a deterministic state machine — that's the deep
dive; the ⚡ chip is live time-to-first-audio."

## Slide 3 — Architecture (1:55–2:35)

**Visual:** the container diagram (ARCHITECTURE.md).

Say: "A modular monolith — FastAPI, one Docker image on Railway, SQLite behind
repositories on a persistent volume. One turn is: Whisper transcribes, gpt-4o-mini
reasons with tools, and TTS *streams* back — audio starts before synthesis finishes.
Moderation screens every input in parallel with the LLM, so safety costs zero latency.
Memory is deliberately boring: every stable fact rides the system prompt — at dozens
of facts per user, retrieval could only add a way to miss. Each piece sits behind a
seam — Postgres, auth, a second search provider are all one-swap changes."

## Slide 4 — Deep dive: the LLM proposes, the FSM disposes (2:35–3:35)

**Visual:** the state diagram + the 6-line legality table from the code.

Say: "The booking workflow is a deterministic finite-state machine; the LLM only
extracts slots and talks. Four guarantees no prompt can give you: tools are legal
per state — confirm outside CONFIRMING is structurally rejected; validation is
per-field — 'party of 250 tomorrow at 8' keeps the date, rejects the size, with a
reason; confirmation needs the user's literal yes — in English or Arabic — so neither
a hallucination nor a prompt injection can ever book; and state persists every turn,
which is why the resume offer you saw works. The whole machine runs its 30+ tests
with zero network. My favorite bug proves the design: Arabic users got stuck in an
infinite confirmation loop — because my affirmation list was English-only. The guard
was *working*; it just needed to learn نعم."

## Slide 5 — Evidence (3:35–4:05)

**Visual:** `/api/metrics` screenshot from production + a test-count strip.

Say: "Measured, not asserted: time-to-first-audio around three and a half seconds —
down from 8.7 before streaming TTS, model tuning, and route warm-up. Server p50 about
2.3 s; the p95 tail is tool-heavy turns on slow provider draws — that's why I report
percentiles. Cost: about four hundredths of a cent per turn. Behind it: 100 tests in
CI, a smoke gate against production, and rate limiting proven live at exactly
request 21."

## Slide 6 — Trade-offs & next week (4:05–4:30) *(droppable)*

**Visual:** two columns.

Chosen: request/response over full-duplex streaming (demo reliability over the last
1.5 s) · SQLite over Postgres (single-writer, zero-ops, seam ready) · prompt-injected
memory over RAG (100% recall at this scale) · deterministic extraction sweep after the
model proved forgetful. Next week: token-streaming into sentence-chunked TTS (~2 s
TTFA) or a speech-to-speech Live API, real reservation partner, barge-in, Postgres +
accounts.

---

## Q&A armory

- **Why not LangGraph/agents framework?** Six states, ~200 auditable lines, testable
  without an LLM. I'd adopt a graph framework at N interacting workflows — not one.
- **Why no RAG?** Dozens of facts ≈ 200 tokens = perfect recall. Retrieval adds a miss
  mode with zero benefit at this scale; I'd add it when memory outgrows the context
  budget. Deliberate, documented (DECISIONS D5).
- **What if the model never saves a memory?** It happened — live testing caught an
  Arabic message saving nothing. Fix: a deterministic background extraction pass after
  every turn, off the critical path. Belt and suspenders, upserts dedupe.
- **Prompt injection?** Three layers: moderation on input, tool outputs framed as
  data (tested with injection strings), and the structural one — no text can force
  `confirm_booking` past the FSM guard.
- **Why is it sometimes slow?** Turn composition (tool rounds, search) + provider tail
  latency. /api/metrics shows the per-stage percentiles; the fix ladder is documented.
- **Double-booking?** COMPLETED is terminal; a second "yes" is structurally illegal.
- **Scaling?** Stateless app: SQLite→Postgres via the repository seam, Redis for rate
  limits, N replicas. The monolith is a choice with exits, not a ceiling.
- **Search quality quirks?** Foursquare free tier: found live that rating/price are
  premium fields (429s from a hidden quota) and its geocoder fails on Cairo districts
  — hence Geoapify geocoding + coordinate search. Real debugging story, happy to
  elaborate.
- **Why root in the container?** Railway mounts volumes root-owned; non-root crashed
  on startup — verified in deploy logs, documented trade-off (D11).

## Omit deliberately

File tree, Pydantic details, CSS, SDK mechanics, the full bug list (keep the two best:
Arabic affirmations, extraction sweep).
