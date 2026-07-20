# ---- builder: install dependencies into an isolated venv ----
FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml ./
COPY app ./app
RUN python -m venv /venv && /venv/bin/pip install --no-cache-dir .

# ---- runtime ----
# Runs as root: Railway mounts volumes root-owned, and a non-root user cannot
# write the SQLite file inside them (verified: startup crash with
# "unable to open database file"). Root-in-container is the standard
# trade-off on volume-backed PaaS; documented in DECISIONS.md.
FROM python:3.12-slim
RUN mkdir -p /data
WORKDIR /srv
COPY --from=builder /venv /venv
COPY app ./app
ENV PATH="/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
# Shell form so Railway's $PORT is honored; defaults to 8000 locally.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
