"""Booking workflow through the real HTTP + orchestrator stack (LLM/Places mocked)."""

import json
import uuid
from datetime import date, timedelta

import httpx
import respx

from tests.conftest import openai_chat_json, openai_tool_call_json

OPENAI_CHAT = "https://api.openai.com/v1/chat/completions"
FSQ = "https://places-api.foursquare.com/places/search"
TOMORROW = (date.today() + timedelta(days=1)).isoformat()

FSQ_JSON = {
    "results": [
        {"name": "La Trattoria", "location": {"formatted_address": "El Mara'ashly St"}},
        {"name": "Vola Vola", "location": {"formatted_address": "Zamalek"}},
    ]
}


def _post(client, text, session_id, user_id):
    return client.post(
        "/api/converse",
        data={"text": text, "session_id": session_id},
        headers={"X-User-Id": user_id},
    )


@respx.mock
def test_full_booking_flow_one_shot_fill(client):
    user_id = str(uuid.uuid4())
    session = str(uuid.uuid4())
    respx.get(FSQ).mock(return_value=httpx.Response(200, json=FSQ_JSON))
    chat = respx.post(OPENAI_CHAT)

    # turn 1: model extracts all slots in one call -> FSM searches -> PRESENTING
    chat.side_effect = [
        httpx.Response(
            200,
            json=openai_tool_call_json(
                "update_booking",
                json.dumps(
                    {"area": "Zamalek", "party_size": 4, "date": TOMORROW, "time": "20:00"}
                ),
            ),
        ),
        httpx.Response(200, json=openai_chat_json("I found La Trattoria and Vola Vola.")),
    ]
    r1 = _post(client, "book a table for 4 in Zamalek tomorrow at 8pm", session, user_id)
    assert r1.status_code == 200
    wf = r1.json()["workflow"]
    assert wf["status"] == "PRESENTING"
    assert [o["name"] for o in wf["options"]] == ["La Trattoria", "Vola Vola"]

    # turn 2: user picks option 1 -> CONFIRMING
    chat.side_effect = [
        httpx.Response(200, json=openai_tool_call_json("select_option", json.dumps({"n": 1}))),
        httpx.Response(
            200, json=openai_chat_json("La Trattoria for 4 tomorrow at 20:00 - shall I book it?")
        ),
    ]
    r2 = _post(client, "the first one please", session, user_id)
    assert r2.json()["workflow"]["status"] == "CONFIRMING"
    assert r2.json()["workflow"]["selected"] == "La Trattoria"

    # turn 3: explicit yes -> COMPLETED
    chat.side_effect = [
        httpx.Response(200, json=openai_tool_call_json("confirm_booking", "{}")),
        httpx.Response(200, json=openai_chat_json("Booked! Enjoy your dinner.")),
    ]
    r3 = _post(client, "yes, book it", session, user_id)
    assert r3.json()["workflow"]["status"] == "COMPLETED"

    # booking is persisted and queryable
    bookings = client.get("/api/bookings", headers={"X-User-Id": user_id}).json()["bookings"]
    assert bookings[0]["status"] == "COMPLETED"
    assert bookings[0]["restaurant"] == "La Trattoria"


@respx.mock
def test_confirm_without_user_yes_is_blocked_by_fsm(client):
    """Even if the model calls confirm_booking, the FSM guard demands a literal yes."""
    user_id = str(uuid.uuid4())
    session = str(uuid.uuid4())
    respx.get(FSQ).mock(return_value=httpx.Response(200, json=FSQ_JSON))
    chat = respx.post(OPENAI_CHAT)

    chat.side_effect = [
        httpx.Response(
            200,
            json=openai_tool_call_json(
                "update_booking",
                json.dumps(
                    {"area": "Zamalek", "party_size": 2, "date": TOMORROW, "time": "19:00"}
                ),
            ),
        ),
        httpx.Response(200, json=openai_chat_json("Options found.")),
    ]
    _post(client, "dinner for two in Zamalek tomorrow 7pm", session, user_id)

    chat.side_effect = [
        httpx.Response(200, json=openai_tool_call_json("select_option", json.dumps({"n": 1}))),
        httpx.Response(200, json=openai_chat_json("Shall I confirm?")),
    ]
    _post(client, "first one", session, user_id)

    # model jumps the gun: calls confirm although the user asked a question
    chat.side_effect = [
        httpx.Response(200, json=openai_tool_call_json("confirm_booking", "{}")),
        httpx.Response(200, json=openai_chat_json("Do you want me to book it - yes or no?")),
    ]
    r = _post(client, "is it expensive there?", session, user_id)
    assert r.json()["workflow"]["status"] == "CONFIRMING"  # NOT completed

    sent = json.loads(respx.calls[-1].request.content)
    tool_msgs = [m for m in sent["messages"] if m["role"] == "tool"]
    assert "not clearly said yes" in tool_msgs[-1]["content"]


@respx.mock
def test_digression_leaves_workflow_untouched(client):
    user_id = str(uuid.uuid4())
    session = str(uuid.uuid4())
    chat = respx.post(OPENAI_CHAT)

    chat.side_effect = [
        httpx.Response(
            200,
            json=openai_tool_call_json("update_booking", json.dumps({"party_size": 4})),
        ),
        httpx.Response(200, json=openai_chat_json("Got it, 4 people. Which area?")),
    ]
    _post(client, "book dinner for 4", session, user_id)

    # off-topic turn: no tools fire
    chat.side_effect = [
        httpx.Response(200, json=openai_chat_json("The capital of Japan is Tokyo. Now - area?")),
    ]
    r = _post(client, "what is the capital of Japan?", session, user_id)
    wf = r.json()["workflow"]
    assert wf["status"] == "COLLECTING"
    assert wf["slots"] == {"party_size": 4}  # untouched


@respx.mock
def test_resume_across_sessions_with_offer(client):
    user_id = str(uuid.uuid4())
    chat = respx.post(OPENAI_CHAT)

    chat.side_effect = [
        httpx.Response(
            200,
            json=openai_tool_call_json(
                "update_booking", json.dumps({"party_size": 4, "area": "Maadi"})
            ),
        ),
        httpx.Response(200, json=openai_chat_json("Which date and time?")),
    ]
    _post(client, "book a table for 4 in Maadi", str(uuid.uuid4()), user_id)

    # NEW session, same user: workflow block must carry state + resume instruction
    chat.side_effect = [
        httpx.Response(200, json=openai_chat_json("Welcome back - continue your Maadi booking?")),
    ]
    r = _post(client, "hey sarjy", str(uuid.uuid4()), user_id)
    assert r.json()["workflow"]["status"] == "COLLECTING"
    assert r.json()["workflow"]["slots"]["area"] == "Maadi"

    sent = json.loads(respx.calls[-1].request.content)
    system = sent["messages"][0]["content"]
    assert "current state: COLLECTING" in system
    assert "area=Maadi" in system
    assert "offer to resume" in system


@respx.mock
def test_mid_booking_search_redirects_into_criteria_change(client):
    """User in CONFIRMING asks 'what about steak in New Cairo?' - even if the
    model reaches for the general search tool, the registry converts it into a
    booking update + re-search instead of a dead end."""
    user_id = str(uuid.uuid4())
    session = str(uuid.uuid4())
    respx.get(FSQ).mock(return_value=httpx.Response(200, json=FSQ_JSON))
    chat = respx.post(OPENAI_CHAT)

    chat.side_effect = [
        httpx.Response(
            200,
            json=openai_tool_call_json(
                "update_booking",
                json.dumps(
                    {"area": "Zamalek", "party_size": 2, "date": TOMORROW, "time": "19:00"}
                ),
            ),
        ),
        httpx.Response(200, json=openai_chat_json("Options found.")),
    ]
    _post(client, "book fish in Zamalek tomorrow 7pm for 2", session, user_id)

    chat.side_effect = [
        httpx.Response(200, json=openai_tool_call_json("select_option", json.dumps({"n": 1}))),
        httpx.Response(200, json=openai_chat_json("Confirm La Trattoria?")),
    ]
    _post(client, "first one", session, user_id)  # now CONFIRMING

    chat.side_effect = [
        httpx.Response(
            200,
            json=openai_tool_call_json(
                "search_restaurants", json.dumps({"query": "steak", "near": "New Cairo"})
            ),
        ),
        httpx.Response(200, json=openai_chat_json("Here are steak options in New Cairo.")),
    ]
    r = _post(client, "what about a steak restaurant in New Cairo?", session, user_id)
    wf = r.json()["workflow"]
    assert wf["status"] == "PRESENTING"  # back to options, selection cleared
    assert wf["slots"]["cuisine"] == "steak"
    assert wf["slots"]["area"] == "New Cairo"
    assert wf["selected"] is None

    sent = json.loads(chat.calls[-1].request.content)
    tool_msgs = [m for m in sent["messages"] if m["role"] == "tool"]
    assert "updated with these criteria" in tool_msgs[-1]["content"]


@respx.mock
def test_confirm_with_named_option_auto_selects(client):
    """User in PRESENTING says 'yes book La Trattoria' and the model jumps
    straight to confirm_booking: the registry auto-selects the named option
    so the confirmation succeeds in one turn."""
    user_id = str(uuid.uuid4())
    session = str(uuid.uuid4())
    respx.get(FSQ).mock(return_value=httpx.Response(200, json=FSQ_JSON))
    chat = respx.post(OPENAI_CHAT)

    chat.side_effect = [
        httpx.Response(
            200,
            json=openai_tool_call_json(
                "update_booking",
                json.dumps(
                    {"area": "Zamalek", "party_size": 2, "date": TOMORROW, "time": "19:00"}
                ),
            ),
        ),
        httpx.Response(200, json=openai_chat_json("Pick one!")),
    ]
    _post(client, "book dinner for 2 in Zamalek tomorrow 7pm", session, user_id)  # PRESENTING

    chat.side_effect = [
        httpx.Response(200, json=openai_tool_call_json("confirm_booking", "{}")),
        httpx.Response(200, json=openai_chat_json("Booked at La Trattoria!")),
    ]
    r = _post(client, "yes, confirm La Trattoria please", session, user_id)
    assert r.json()["workflow"]["status"] == "COMPLETED"
    assert r.json()["workflow"]["selected"] == "La Trattoria"


@respx.mock
def test_booking_history_injected_into_prompt(client):
    """A completed booking is visible to the model in later turns, so
    'what are my bookings?' answers from data."""
    user_id = str(uuid.uuid4())
    session = str(uuid.uuid4())
    respx.get(FSQ).mock(return_value=httpx.Response(200, json=FSQ_JSON))
    chat = respx.post(OPENAI_CHAT)

    chat.side_effect = [
        httpx.Response(
            200,
            json=openai_tool_call_json(
                "update_booking",
                json.dumps(
                    {"area": "Zamalek", "party_size": 4, "date": TOMORROW, "time": "20:00"}
                ),
            ),
        ),
        httpx.Response(200, json=openai_chat_json("Options!")),
    ]
    _post(client, "book for 4 in Zamalek tomorrow 8pm", session, user_id)
    chat.side_effect = [
        httpx.Response(200, json=openai_tool_call_json("select_option", json.dumps({"n": 1}))),
        httpx.Response(200, json=openai_chat_json("Confirm?")),
    ]
    _post(client, "first one", session, user_id)
    chat.side_effect = [
        httpx.Response(200, json=openai_tool_call_json("confirm_booking", "{}")),
        httpx.Response(200, json=openai_chat_json("Booked!")),
    ]
    _post(client, "yes", session, user_id)

    chat.side_effect = [
        httpx.Response(200, json=openai_chat_json("You have one booking at La Trattoria.")),
    ]
    _post(client, "what bookings do I have?", session, user_id)
    system = json.loads(chat.calls[-1].request.content)["messages"][0]["content"]
    assert "This user's bookings" in system
    assert "COMPLETED: La Trattoria" in system


@respx.mock
def test_illegal_tool_call_blocked_by_legality_table(client):
    """select_option before any booking exists -> registry blocks it via the FSM."""
    user_id = str(uuid.uuid4())
    chat = respx.post(OPENAI_CHAT)
    chat.side_effect = [
        httpx.Response(200, json=openai_tool_call_json("select_option", json.dumps({"n": 1}))),
        httpx.Response(200, json=openai_chat_json("Let's start a booking first.")),
    ]
    r = _post(client, "pick the first option", str(uuid.uuid4()), user_id)
    assert r.status_code == 200
    sent = json.loads(respx.calls[-1].request.content)
    tool_msgs = [m for m in sent["messages"] if m["role"] == "tool"]
    assert "not allowed" in tool_msgs[0]["content"]
