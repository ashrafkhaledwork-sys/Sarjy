import logging

from openai import OpenAI, OpenAIError

# Pre-load the SDK's lazily-imported resource modules on the main thread.
# Moderation runs on a worker thread; concurrent lazy imports deadlock
# (_frozen_importlib._DeadlockError seen in tests).
from openai.resources import chat as _preload_chat  # noqa: F401
from openai.resources import moderations as _preload_moderations  # noqa: F401
from openai.resources.audio import speech as _preload_speech  # noqa: F401
from openai.resources.audio import transcriptions as _preload_stt  # noqa: F401

from app.config import settings
from app.core.errors import AppError

logger = logging.getLogger(__name__)

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=settings.openai_api_key or "unset",
            timeout=30.0,
            max_retries=2,
        )
    return _client


def chat(messages: list[dict], tools: list[dict] | None = None):
    """One chat-completion call. Returns the assistant message object
    (content and, later, tool_calls). Raises AppError on provider failure."""
    kwargs: dict = {"model": settings.openai_chat_model, "messages": messages}
    if tools:
        kwargs["tools"] = tools
    try:
        resp = client().chat.completions.create(**kwargs)
    except OpenAIError as exc:
        # Root cause must reach the logs even though the user gets a soft reply.
        logger.error("OpenAI chat failed: %s: %s", type(exc).__name__, exc)
        raise AppError(
            "llm_unavailable",
            "I'm having trouble thinking right now - please try again in a moment.",
            status=503,
        ) from exc
    return resp.choices[0].message
