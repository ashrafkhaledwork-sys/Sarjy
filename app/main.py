import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from app.api.routes import router as api_router
from app.config import APP_VERSION, settings
from app.core.errors import AppError
from app.core.logging_setup import configure as configure_logging
from app.core.logging_setup import request_id_var
from app.core.ratelimit import limiter
from app.db.engine import db_ping, init_db

configure_logging(settings.log_level)

STATIC_DIR = Path(__file__).parent / "static"


class NoCacheStaticFiles(StaticFiles):
    """Serve static assets with revalidation. The files are tiny, and a stale
    cached app.js during a live demo is a far worse cost than an ETag check."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def _warm_openai_loop() -> None:
    """Keep the OpenAI connections AND model routes warm so no user turn pays
    cold-start costs (measured: first turn 8.7 s cold vs ~3.5 s warm).
    Route warming costs ~$0.04/day - the cheapest latency win there is."""
    import time as _time

    from app.services.llm import client

    while True:
        try:
            c = client().with_options(max_retries=0)
            c.chat.completions.create(
                model=settings.openai_chat_model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            c.audio.speech.create(
                model=settings.openai_tts_model,
                voice=settings.openai_tts_voice,
                input="hi",
                response_format="mp3",
            ).read()
        except Exception as exc:  # noqa: BLE001 - warm-up must never crash the app
            logging.getLogger(__name__).debug("warm-up ping failed: %s", exc)
        _time.sleep(240)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        from app.db.engine import open_session
        from app.db.repositories import MetricsRepo

        db = open_session()
        MetricsRepo(db).prune(days=30)
        db.close()
    except Exception:  # noqa: BLE001 - retention cleanup must never block startup
        logging.getLogger(__name__).warning("metrics prune failed", exc_info=True)
    if settings.app_env not in ("test",) and settings.openai_api_key:
        import threading

        threading.Thread(target=_warm_openai_loop, daemon=True, name="openai-warm").start()
    yield


def _error_envelope(request: Request, code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": getattr(request.state, "request_id", "unknown"),
            }
        },
    )


def create_app() -> FastAPI:
    app = FastAPI(title="Sarjy", version=APP_VERSION, lifespan=lifespan)
    app.state.limiter = limiter

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex[:12]
        token = request_id_var.set(request.state.request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-Id"] = request.state.request_id
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return _error_envelope(request, exc.code, exc.message, exc.status)

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        return _error_envelope(
            request, "rate_limited", "Too many requests - give it a minute.", 429
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        # Whatever breaks, the client gets the envelope - never a stack trace.
        logging.getLogger(__name__).exception("unhandled error: %s", exc)
        return _error_envelope(
            request, "internal_error", "Something went wrong on our side.", 500
        )

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "version": APP_VERSION}

    @app.get("/readyz")
    def readyz() -> dict:
        return {"status": "ready" if db_ping() else "degraded"}

    app.include_router(api_router)
    # Static mount is registered last so /api/* and health routes take precedence.
    app.mount("/", NoCacheStaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


app = create_app()
