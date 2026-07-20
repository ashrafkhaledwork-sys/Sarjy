"""Phase 9-10 hardening: rate limits, forget-everything, catch-all envelope."""

import uuid

import httpx
import respx

from tests.conftest import openai_chat_json

OPENAI_CHAT = "https://api.openai.com/v1/chat/completions"


@respx.mock
def test_converse_rate_limit_trips_at_21(client):
    from app.core.ratelimit import limiter

    limiter.enabled = True
    try:
        _run_rate_limit_scenario(client)
    finally:
        limiter.enabled = False


def _run_rate_limit_scenario(client):
    respx.post(OPENAI_CHAT).mock(
        return_value=httpx.Response(200, json=openai_chat_json("ok"))
    )
    user_id = str(uuid.uuid4())
    statuses = []
    for _ in range(21):
        r = client.post(
            "/api/converse",
            data={"text": "hi", "session_id": str(uuid.uuid4())},
            headers={"X-User-Id": user_id},
        )
        statuses.append(r.status_code)

    assert statuses[:20] == [200] * 20
    assert statuses[20] == 429
    body_error = r.json()["error"]
    assert body_error["code"] == "rate_limited"
    assert "request_id" in body_error


def test_forget_everything(client):
    from app.db import engine
    from app.db.repositories import MemoryRepo

    user_id = str(uuid.uuid4())
    db = engine.open_session()
    repo = MemoryRepo(db)
    repo.upsert(user_id, "identity", "name", "Ashraf")
    repo.upsert(user_id, "preference", "favorite_color", "blue")
    db.close()

    r = client.delete("/api/memories", headers={"X-User-Id": user_id})
    assert r.status_code == 200
    assert r.json()["deleted"] == 2

    listed = client.get("/api/memories", headers={"X-User-Id": user_id}).json()
    assert listed["memories"] == []


def test_unhandled_error_returns_envelope_not_traceback(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    def boom(*args, **kwargs):
        raise RuntimeError("database exploded")

    monkeypatch.setattr("app.api.routes.run_text_turn", boom)
    # raise_server_exceptions=False lets the app's own 500 handler answer,
    # exactly as it does under uvicorn.
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post(
            "/api/converse",
            data={"text": "hi", "session_id": str(uuid.uuid4())},
            headers={"X-User-Id": str(uuid.uuid4())},
        )
    assert r.status_code == 500
    body = r.json()
    assert body["error"]["code"] == "internal_error"
    assert "database exploded" not in r.text  # no leak
    assert "Traceback" not in r.text
