import logging
from dataclasses import dataclass
from typing import Any

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


@dataclass
class ChatResult:
    """The assistant message plus token usage for cost tracking."""

    message: Any
    usage_in: int = 0
    usage_out: int = 0

    @property
    def content(self):
        return self.message.content

    @property
    def tool_calls(self):
        return self.message.tool_calls


def chat(messages: list[dict], tools: list[dict] | None = None) -> ChatResult:
    """One chat-completion call. Raises AppError on provider failure."""
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
    usage = getattr(resp, "usage", None)
    return ChatResult(
        message=resp.choices[0].message,
        usage_in=getattr(usage, "prompt_tokens", 0) or 0,
        usage_out=getattr(usage, "completion_tokens", 0) or 0,
    )
