# ---- builder: install dependencies into an isolated venv ----
FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml ./
COPY app ./app
RUN python -m venv /venv && /venv/bin/pip install --no-cache-dir .

# ---- runtime: slim image, non-root user ----
FROM python:3.12-slim
RUN useradd --create-home sarjy && mkdir /data && chown sarjy:sarjy /data
WORKDIR /srv
COPY --from=builder /venv /venv
COPY app ./app
USER sarjy
ENV PATH="/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
# Shell form so Railway's $PORT is honored; defaults to 8000 locally.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
