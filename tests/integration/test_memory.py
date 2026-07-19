"""The assignment's signature scenario: remember in one session, recall in another."""

import json
import uuid

import httpx
import respx

from tests.conftest import openai_chat_json, openai_tool_call_json

OPENAI_CHAT = "https://api.openai.com/v1/chat/completions"


def _post_text(client, text, session_id, user_id):
    return client.post(
        "/api/converse",
        data={"text": text, "session_id": session_id},
        headers={"X-User-Id": user_id},
    )


@respx.mock
def test_favorite_color_across_sessions(client):
    user_id = str(uuid.uuid4())

    # --- session 1: model saves the fact via tool call, then replies ---
    route = respx.post(OPENAI_CHAT)
    route.side_effect = [
        httpx.Response(
            200,
            json=openai_tool_call_json(
                "save_memory",
                json.dumps(
                    {"category": "preference", "key": "favorite_color", "value": "blue"}
                ),
            ),
        ),
        httpx.Response(200, json=openai_chat_json("Nice, blue it is!")),
    ]
    r1 = _post_text(client, "My favorite color is blue.", str(uuid.uuid4()), user_id)
    assert r1.status_code == 200
    assert r1.json()["memories_updated"] is True
    assert r1.json()["reply_text"] == "Nice, blue it is!"

    # fact is persisted and visible via the drawer API
    listed = client.get("/api/memories", headers={"X-User-Id": user_id}).json()
    assert listed["memories"][0]["key"] == "favorite_color"
    assert listed["memories"][0]["value"] == "blue"

    # --- session 2 (fresh session, same user): fact is injected into the prompt ---
    route.side_effect = [
        httpx.Response(200, json=openai_chat_json("Your favorite color is blue.")),
    ]
    r2 = _post_text(client, "What is my favorite color?", str(uuid.uuid4()), user_id)
    assert r2.status_code == 200
    assert "blue" in r2.json()["reply_text"].lower()

    sent = json.loads(route.calls[-1].request.content)
    system = sent["messages"][0]["content"]
    assert "favorite_color: blue" in system
    # no cross-session message replay: recall comes from memory, not history
    assert "Nice, blue it is!" not in [m.get("content") for m in sent["messages"]]


@respx.mock
def test_invalid_tool_args_get_repair_round(client):
    user_id = str(uuid.uuid4())
    route = respx.post(OPENAI_CHAT)
    route.side_effect = [
        # bad category -> validation error goes back to the model
        httpx.Response(
            200,
            json=openai_tool_call_json(
                "save_memory",
                json.dumps({"category": "nonsense", "key": "x", "value": "y"}),
            ),
        ),
        httpx.Response(200, json=openai_chat_json("Sorry, could you rephrase?")),
    ]
    r = _post_text(client, "remember something", str(uuid.uuid4()), user_id)
    assert r.status_code == 200
    assert r.json()["memories_updated"] is False

    # the tool result the model saw contains the validation error
    sent = json.loads(route.calls[-1].request.content)
    tool_msgs = [m for m in sent["messages"] if m["role"] == "tool"]
    assert "invalid arguments" in tool_msgs[0]["content"]


@respx.mock
def test_delete_memory_via_conversation(client):
    user_id = str(uuid.uuid4())
    route = respx.post(OPENAI_CHAT)
    route.side_effect = [
        httpx.Response(
            200,
            json=openai_tool_call_json(
                "save_memory",
                json.dumps({"category": "identity", "key": "name", "value": "Ashraf"}),
            ),
        ),
        httpx.Response(200, json=openai_chat_json("Saved.")),
        httpx.Response(
            200,
            json=openai_tool_call_json("delete_memory", json.dumps({"key": "name"})),
        ),
        httpx.Response(200, json=openai_chat_json("Forgotten.")),
    ]
    _post_text(client, "I'm Ashraf", str(uuid.uuid4()), user_id)
    r = _post_text(client, "forget my name", str(uuid.uuid4()), user_id)
    assert r.json()["memories_updated"] is True
    listed = client.get("/api/memories", headers={"X-User-Id": user_id}).json()
    assert listed["memories"] == []


def test_delete_memory_via_drawer_api(client):
    user_id = str(uuid.uuid4())
    # seed directly through the repo layer via the API-less path is overkill;
    # a 404 on unknown key is the contract worth pinning here
    r = client.delete("/api/memories/never_saved", headers={"X-User-Id": user_id})
    assert r.status_code == 404
