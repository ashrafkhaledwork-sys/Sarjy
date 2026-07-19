"""External-API requirement: real data flows in via the tool, never invented."""

import json
import uuid

import httpx
import respx

from tests.conftest import openai_chat_json, openai_tool_call_json

OPENAI_CHAT = "https://api.openai.com/v1/chat/completions"
FSQ = "https://places-api.foursquare.com/places/search"


def _post_text(client, text):
    return client.post(
        "/api/converse",
        data={"text": text, "session_id": str(uuid.uuid4())},
        headers={"X-User-Id": str(uuid.uuid4())},
    )


@respx.mock
def test_restaurant_results_reach_the_model_as_tool_data(client):
    respx.get(FSQ).mock(
        return_value=httpx.Response(
            200,
            json={"results": [{"name": "Zooba", "location": {"formatted_address": "Zamalek"}}]},
        )
    )
    chat = respx.post(OPENAI_CHAT)
    chat.side_effect = [
        httpx.Response(
            200,
            json=openai_tool_call_json(
                "search_restaurants", json.dumps({"near": "Cairo", "query": "egyptian"})
            ),
        ),
        httpx.Response(200, json=openai_chat_json("How about Zooba in Zamalek?")),
    ]

    r = _post_text(client, "find me egyptian food in Cairo")
    assert r.status_code == 200
    assert "Zooba" in r.json()["reply_text"]

    # the restaurant entered the conversation ONLY as a tool result
    sent = json.loads(chat.calls[-1].request.content)
    tool_msgs = [m for m in sent["messages"] if m["role"] == "tool"]
    assert "Zooba" in tool_msgs[0]["content"]
    assert "Zooba" not in sent["messages"][0]["content"]  # never in the system prompt


@respx.mock
def test_places_outage_reaches_model_as_error_marker(client):
    respx.get(FSQ).mock(return_value=httpx.Response(503))
    chat = respx.post(OPENAI_CHAT)
    chat.side_effect = [
        httpx.Response(
            200,
            json=openai_tool_call_json("search_restaurants", json.dumps({"near": "Cairo"})),
        ),
        httpx.Response(
            200, json=openai_chat_json("Restaurant search is unavailable right now, sorry.")
        ),
    ]

    r = _post_text(client, "find me food")
    assert r.status_code == 200  # turn still succeeds

    sent = json.loads(chat.calls[-1].request.content)
    tool_msgs = [m for m in sent["messages"] if m["role"] == "tool"]
    assert json.loads(tool_msgs[0]["content"]) == {"error": "search_unavailable"}


@respx.mock
def test_missing_near_argument_gets_repair_round(client):
    chat = respx.post(OPENAI_CHAT)
    chat.side_effect = [
        httpx.Response(
            200, json=openai_tool_call_json("search_restaurants", json.dumps({}))
        ),
        httpx.Response(200, json=openai_chat_json("Which area should I search in?")),
    ]
    r = _post_text(client, "find me food")
    assert r.status_code == 200
    sent = json.loads(chat.calls[-1].request.content)
    tool_msgs = [m for m in sent["messages"] if m["role"] == "tool"]
    assert "invalid arguments" in tool_msgs[0]["content"]
