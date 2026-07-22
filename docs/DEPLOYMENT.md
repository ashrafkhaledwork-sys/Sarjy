# Deployment

Production: **Railway**, deploying the repo's Dockerfile from GitHub.
Live at https://sarjy-production-3bc0.up.railway.app

## Why Railway
Dockerfile-native, persistent volumes, automatic HTTPS + domain, no cold starts
(Render's free tier spins down — a 30–60 s cold start in front of reviewers), secrets
UI, one-click rollback to any previous deploy.

## Setup from scratch

1. **New Project → Deploy from GitHub repo** → pick the repo. Railway auto-detects the
   Dockerfile and builds on every push.
2. **Variables** (service → Variables → raw editor): paste `.env` contents, then set
   `DATABASE_URL=sqlite:////data/sarjy.db` (four slashes — absolute path on the
   volume). Do **not** set `PORT`; Railway injects it and the Dockerfile honors it.
3. **Volume**: right-click the service → Attach Volume → mount path `/data`.
   Without it the SQLite file dies with every deploy. (Verified behavior: a memory
   planted before a redeploy survived it.)
4. **Domain**: Settings → Networking → Generate Domain.
5. **Verify**: `python scripts/smoke_test.py https://<domain>` → expect `SMOKE PASSED`.

## Environment variables

| Var | Notes |
|---|---|
| `OPENAI_API_KEY` | required — STT, chat, TTS, moderation |
| `OPENAI_CHAT_MODEL` / `OPENAI_STT_MODEL` / `OPENAI_TTS_MODEL` / `OPENAI_TTS_VOICE` | defaults: gpt-4o-mini / gpt-4o-mini-transcribe / gpt-4o-mini-tts / alloy |
| `PLACES_PROVIDER` | `foursquare` (default) or `geoapify` — the demo-day escape hatch |
| `FOURSQUARE_API_KEY` / `GEOAPIFY_API_KEY` | at least one; Geoapify also powers geocoding |
| `DATABASE_URL` | `sqlite:////data/sarjy.db` in prod; `sqlite:///./data/sarjy.db` locally |
| `RATE_LIMIT_ENABLED` | default `true` |
| `APP_ENV` / `LOG_LEVEL` | `dev`/`INFO` defaults |

## Operational notes

- **Image**: multi-stage (`python:3.12-slim`), venv copied into a slim runtime,
  container healthcheck on `/healthz`. Runs as root — Railway mounts volumes
  root-owned; a non-root user cannot create the DB file (see DECISIONS.md D11).
- **Migrations**: `create_all` on startup (additive schema); metrics rows pruned to
  30 days at boot.
- **Warm-up**: a background thread pings the chat + TTS routes every 4 minutes
  (~$0.04/day) so no user ever pays OpenAI's cold-path latency — including the first
  demo turn.
- **CI**: GitHub Actions on every push — ruff, pytest (100 tests), docker build.
  Deploys are Railway-automatic on push to main; post-deploy verification is the smoke
  script.
- **Rollback**: Railway → Deployments → previous build → Redeploy. The volume (and
  therefore all user data) is untouched by rollbacks.
- **Logs**: Railway → View Logs. Every line carries a request id; each turn logs a
  one-line summary (stages, tokens, workflow state). Transcript bodies are never
  logged at INFO.

## Local parity

`docker compose up --build` runs the same image with a named volume at `/data` —
the production topology on your laptop, and the demo-day fallback if the internet
hates you (see DEMO.md).
