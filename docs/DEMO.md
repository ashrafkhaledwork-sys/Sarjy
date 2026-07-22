# Demo runbook

Target: the live demo fits in **90 seconds of conversation** inside the 5-minute
presentation. Everything here is rehearsable and has a fallback.

## Pre-demo checklist (T-30 minutes)

- [ ] `python scripts/smoke_test.py https://sarjy-production-3bc0.up.railway.app` → SMOKE PASSED
- [ ] `python scripts/seed_demo.py https://sarjy-production-3bc0.up.railway.app` → prints the **returning-user id** — set it in the second browser/incognito (console: `localStorage.setItem("sarjy_user_id", "<id>")`)
- [ ] Demo tab open at the prod URL **with `?debug`** (live latency chips on stage); reviewer-facing plain URL in a second tab
- [ ] Phone charged, on the venue wifi *and* hotspot tested; volume up on the demo device
- [ ] Backup video downloaded locally (not just a Loom link)

## Primary script (~90 s, hands-free after one tap)

1. **Memory + bilingual** — tap the orb once:
   *"Hi Sarjy — I'm ‹name›, my favorite color is blue and I love Italian food."*
   → reply + "memory updated" chip. Open the Memories drawer for 2 seconds — facts
   visible, deletable.
2. **The workflow** — keep talking (mic reopened itself):
   *"Book me a dinner tomorrow at 8 PM in Zamalek."* → panel shows
   `BOOKING · COLLECTING`; it asks party size.
   **Digression:** *"Wait — what's the capital of Japan?"* → answers, panel unchanged
   → *"4 people."* → real restaurants, panel `PRESENTING`.
   **Correction:** *"Actually make it 6, and take the first one."* → re-search +
   selection chained, `CONFIRMING`, full read-back with "8 PM".
   *"Yes, book it!"* → `BOOKED ✓`.
3. **Cross-session memory** — switch to the seeded browser:
   *"What's my favorite color?"* → "Blue." *"Do I have any bookings?"* → recalls it;
   the seeded unfinished booking triggers *"welcome back — continue your booking?"*
4. **If time allows (+20 s):** one Arabic line — *"احجزلي سوشي في التجمع بكرة"* —
   or attach a phone photo: *"book for the number of people in this picture."*

## Fallback ladder

| Failure | Move |
|---|---|
| Mic denied / noisy room | Type instead — every voice feature works from the text box; Sarjy still speaks |
| Arabic TTS accent disappoints | Stay in English; mention bilingual with the screenshot in the pre-read |
| Foursquare down | It fails *honestly* on stage (that's a feature — say so), or flip `PLACES_PROVIDER=geoapify` in Railway variables (~30 s redeploy) |
| OpenAI down | Play the backup video, narrate over it |
| Railway down | `docker compose up` on the laptop — same app, localhost |
| Everything down | Backup video + the metrics/architecture slides carry the talk |

## Seeding

`scripts/seed_demo.py <base-url>` creates a fresh user with memories
(name, favorite color blue, Italian preference) and one **unfinished** booking
(Maadi, party 2 — missing date/time) so the resume offer fires on camera. Prints the
user id; it's safe to re-run (fresh user each time).

## Talking points while things load

- The panel is the FSM made visible — "the LLM proposes, this state machine disposes."
- The ⚡ chip is real: "first audio in ~3.5 s — reply text lands at ~2, audio streams
  before synthesis finishes."
- If a slow turn happens live: "that's a tool-heavy turn plus OpenAI's p95 tail —
  here's the percentile breakdown on /api/metrics."
