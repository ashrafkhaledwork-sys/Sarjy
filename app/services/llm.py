import logging

from openai import OpenAI, OpenAIError

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
