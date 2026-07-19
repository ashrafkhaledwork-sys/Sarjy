"""Test env is pinned BEFORE any app import: throwaway DB, fake OpenAI key.

Env vars take precedence over .env in pydantic-settings, so tests can never
touch the real database or spend real API credit.
"""

import os
import tempfile

_db_fd, _db_path = tempfile.mkstemp(prefix="sarjy_test_", suffix=".db")
os.close(_db_fd)
os.environ["DATABASE_URL"] = "sqlite:///" + _db_path.replace("\\", "/")
os.environ["OPENAI_API_KEY"] = "sk-test-not-a-real-key"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    # Context manager runs lifespan (init_db) against the throwaway DB.
    with TestClient(app) as c:
        yield c


def openai_chat_json(content: str) -> dict:
    """Minimal valid chat-completion payload for respx mocks."""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def openai_tool_call_json(name: str, arguments: str, call_id: str = "call_1") -> dict:
    """Chat-completion payload where the model requests one tool call."""
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
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
