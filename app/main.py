from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import APP_VERSION

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="Sarjy", version=APP_VERSION)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "version": APP_VERSION}

    # API routers are registered before the static mount so /api/* and /healthz
    # take precedence over the catch-all static handler.
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


app = create_app()
