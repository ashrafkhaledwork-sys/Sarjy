# Sarjy

A web voice assistant that **remembers you** and **plans dinner for you**. Talk to it in the
browser; it answers by voice, keeps stable facts about you across sessions, and runs a
multistep restaurant-booking workflow backed by real restaurant data.

> Status: under construction (Phase 2 of the build plan — skeleton).

## Quickstart (local)

```bash
cp .env.example .env   # fill in your keys
docker compose up --build
# open http://localhost:8000
```

Dev mode without Docker:

```bash
python -m venv .venv
.venv/Scripts/pip install -e .[dev]      # Windows (POSIX: .venv/bin/pip)
.venv/Scripts/python -m uvicorn app.main:app --reload
```

Verify your API keys before building further:

```bash
python scripts/verify_keys.py "Cairo"    # pass your demo city
```

## Documentation

Full docs land in `docs/` (architecture, decisions, deployment, testing, demo, limitations)
as the build progresses.
