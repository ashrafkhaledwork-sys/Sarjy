import uuid

import httpx
import respx

from tests.conftest import openai_chat_json

OPENAI_CHAT = "https://api.openai.com/v1/chat/completions"


def _headers():
    return {"X-User-Id": str(uuid.uuid4())}


@respx.mock
def test_text_turn_roundtrip(client):
    respx.post(OPENAI_CHAT).mock(
        return_value=httpx.Response(200, json=openai_chat_json("Hello! How can I help?"))
    )
    session_id = str(uuid.uuid4())
    r = client.post(
        "/api/converse",
        data={"text": "hi there", "session_id": session_id},
        headers=_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["transcript"] == "hi there"
    assert body["reply_text"] == "Hello! How can I help?"
    assert body["workflow"]["status"] == "IDLE"
    assert body["timings"]["total_ms"] >= 0
    assert r.headers["X-Request-Id"] == body["request_id"]


@respx.mock
def test_history_sent_to_llm_across_turns(client):
    route = respx.post(OPENAI_CHAT).mock(
        return_value=httpx.Response(200, json=openai_chat_json("ok"))
    )
    headers = _headers()
    session_id = str(uuid.uuid4())
    client.post("/api/converse", data={"text": "first", "session_id": session_id}, headers=headers)
    client.post("/api/converse", data={"text": "second", "session_id": session_id}, headers=headers)

    import json

    sent = json.loads(route.calls[-1].request.content)
    contents = [m["content"] for m in sent["messages"]]
    assert contents[0].startswith("You are Sarjy")  # system prompt first
    # second call carries the full first exchange as history
    assert "first" in contents
    assert "ok" in contents
    assert contents[-1] == "second"


def test_missing_user_header_rejected(client):
    r = client.post(
        "/api/converse", data={"text": "hi", "session_id": str(uuid.uuid4())}
    )
    assert r.status_code == 422


def test_invalid_user_id_rejected(client):
    r = client.post(
        "/api/converse",
        data={"text": "hi", "session_id": str(uuid.uuid4())},
        headers={"X-User-Id": "not-a-uuid"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_input"


def test_empty_text_rejected(client):
    r = client.post(
        "/api/converse",
        data={"text": "   ", "session_id": str(uuid.uuid4())},
        headers=_headers(),
    )
    assert r.status_code == 400


@respx.mock
def test_llm_failure_returns_honest_503(client):
    respx.post(OPENAI_CHAT).mock(return_value=httpx.Response(500, json={"error": "boom"}))
    r = client.post(
        "/api/converse",
        data={"text": "hi", "session_id": str(uuid.uuid4())},
        headers=_headers(),
    )
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "llm_unavailable"
