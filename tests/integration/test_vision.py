"""Multimodal: attached images reach the model this turn, never bloat history."""

import json
import uuid

import httpx
import respx

from tests.conftest import openai_chat_json

OPENAI_CHAT = "https://api.openai.com/v1/chat/completions"

FAKE_JPEG = b"\xff\xd8\xff\xe0fakejpegbytes"


def _post_image(client, text, session_id, user_id):
    return client.post(
        "/api/converse",
        data={"text": text, "session_id": session_id},
        files={"image": ("photo.jpg", FAKE_JPEG, "image/jpeg")},
        headers={"X-User-Id": user_id},
    )


@respx.mock
def test_image_rides_current_turn_as_data_url(client):
    chat = respx.post(OPENAI_CHAT).mock(
        return_value=httpx.Response(200, json=openai_chat_json("I see a menu."))
    )
    r = _post_image(client, "what is this?", str(uuid.uuid4()), str(uuid.uuid4()))
    assert r.status_code == 200
    assert r.json()["reply_text"] == "I see a menu."

    sent = json.loads(chat.calls[0].request.content)
    last_user = [m for m in sent["messages"] if m["role"] == "user"][-1]
    assert isinstance(last_user["content"], list)
    assert last_user["content"][0] == {"type": "text", "text": "what is this?"}
    assert last_user["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


@respx.mock
def test_history_keeps_marker_not_image(client):
    chat = respx.post(OPENAI_CHAT).mock(
        return_value=httpx.Response(200, json=openai_chat_json("ok"))
    )
    session_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    _post_image(client, "look at this menu", session_id, user_id)

    client.post(
        "/api/converse",
        data={"text": "thanks", "session_id": session_id},
        headers={"X-User-Id": user_id},
    )
    sent = json.loads(chat.calls[-1].request.content)
    user_msgs = [m for m in sent["messages"] if m["role"] == "user"]
    # earlier image turn is a plain text marker now - no base64 in history
    assert user_msgs[0]["content"] == "look at this menu [image attached]"
    assert "base64" not in json.dumps(user_msgs[0])


@respx.mock
def test_image_only_message_allowed(client):
    respx.post(OPENAI_CHAT).mock(
        return_value=httpx.Response(200, json=openai_chat_json("A pyramid!"))
    )
    r = client.post(
        "/api/converse",
        data={"session_id": str(uuid.uuid4())},
        files={"image": ("p.jpg", FAKE_JPEG, "image/jpeg")},
        headers={"X-User-Id": str(uuid.uuid4())},
    )
    assert r.status_code == 200


def test_non_image_upload_rejected(client):
    r = client.post(
        "/api/converse",
        data={"text": "hi", "session_id": str(uuid.uuid4())},
        files={"image": ("evil.exe", b"MZbinary", "application/octet-stream")},
        headers={"X-User-Id": str(uuid.uuid4())},
    )
    assert r.status_code == 400
    assert "image" in r.json()["error"]["message"]
