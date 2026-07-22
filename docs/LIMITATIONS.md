# Limitations

Honest list — each with the reasoning and what would fix it.

1. **Bookings are simulated.** The workflow ends in a persisted, confirmed record —
   no real reservation is placed (OpenTable-style APIs have no open access in Egypt).
   The FSM's confirmation gate is exactly where a real reservation call would go.

2. **Identity is the browser, not the person.** Anonymous UUID in localStorage:
   clearing site data mints a new identity; two people sharing a browser share a
   memory; the same person on phone + laptop is two users. Right trade-off for a
   public demo (zero friction, per-visitor isolation); accounts would attach at the
   existing user/session seam.

3. **Turn-based latency floor ~3 s.** Sequential STT → LLM → first TTS chunk. Every
   cheap lever is pulled (streamed TTS, parallel moderation, route warm-up, fast
   models); the next real gain is token-streaming into sentence-chunked TTS or a
   speech-to-speech architecture — a deliberate non-goal for a 2-day, demo-critical
   build. p95 tails (~11 s) come from tool-heavy turns on slow provider draws.

4. **No barge-in over voice.** You can tap the orb to interrupt Sarjy, but it won't
   hear you speak over it (that's full-duplex territory, same trade-off as #3).

5. **VAD is energy-based.** Tuned thresholds (1.2 s pause = end of utterance) work in
   quiet-to-moderate rooms; loud cafés may need the tap-to-send fallback that always
   works. A model-based VAD would be the upgrade.

6. **Memory has no version history.** Newest value wins on conflict ("actually it's
   green" just overwrites). Sensible for stable facts; an audit trail would need an
   event-sourced memory table.

7. **Attached images live for one turn.** By design (history stays lean, and old
   base64 never bloats the context); Sarjy uses what it learned in-conversation but
   can't re-inspect an old photo — it asks you to re-attach instead.

8. **Restaurant data quality = Foursquare's Cairo coverage.** Generally strong
   (malls, chains, Arabic names), but ratings/prices are premium-tier fields we don't
   request on the free plan, and occasional oddities surface (a café in a "meat"
   search). Mitigated by cuisine-keyword guidance; a paid tier or second data source
   would improve it.

9. **Single instance.** In-memory rate-limit counters and the speech reply cache are
   per-process; SQLite is single-writer. Scaling out means Postgres + Redis — both
   sit behind existing seams (repositories, cache module).

10. **English + Egyptian Arabic only** are actively supported and tested; other
    languages may partially work (the models are multilingual) but are unverified.
