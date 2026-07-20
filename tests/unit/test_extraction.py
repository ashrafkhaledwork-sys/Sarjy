import json
import uuid

import httpx
import pytest
import respx

from app.core.extraction import sweep
from app.db import engine
from app.db.repositories import MemoryRepo
from tests.conftest import openai_chat_json

OPENAI_CHAT = "https://api.openai.com/v1/chat/completions"


@pytest.fixture()
def db():
    engine.init_db("sqlite:///:memory:")
    gen = engine.get_db()
    session = next(gen)
    yield session
    session.close()


def _two_fact_response() -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {
                                "name": "save_memory",
                                "arguments": json.dumps(
                                    {"category": "identity", "key": "name", "value": "Ashraf"}
                                ),
                            },
                        },
                        {
                            "id": "c2",
                            "type": "function",
                            "function": {
                                "name": "save_memory",
                                "arguments": json.dumps(
                                    {
                                        "category": "preference",
                                        "key": "favorite_food",
                                        "value": "pizza",
                                    }
                                ),
                            },
                        },
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


@respx.mock
def test_sweep_saves_extracted_facts(db):
    respx.post(OPENAI_CHAT).mock(return_value=httpx.Response(200, json=_two_fact_response()))
    user_id = str(uuid.uuid4())
    assert sweep(user_id, "أنا اسمي أشرف وبحب البيتزا") == 2
    keys = {m.key: m.value for m in MemoryRepo(db).list_for_user(user_id)}
    assert keys == {"name": "Ashraf", "favorite_food": "pizza"}


@respx.mock
def test_sweep_no_facts_saves_nothing(db):
    respx.post(OPENAI_CHAT).mock(return_value=httpx.Response(200, json=openai_chat_json("none")))
    user_id = str(uuid.uuid4())
    assert sweep(user_id, "what's the weather like today?") == 0
    assert MemoryRepo(db).list_for_user(user_id) == []


@respx.mock
def test_sweep_survives_llm_outage(db):
    respx.post(OPENAI_CHAT).mock(return_value=httpx.Response(500))
    assert sweep(str(uuid.uuid4()), "my name is Ashraf") == 0  # never raises


def test_sweep_skips_trivial_text(db):
    assert sweep(str(uuid.uuid4()), "hi") == 0
