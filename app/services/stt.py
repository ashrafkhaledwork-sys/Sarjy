import logging
from time import perf_counter

from openai import OpenAIError

from app.config import settings
from app.core.errors import AppError
from app.services.llm import client

logger = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 10 * 1024 * 1024


def transcribe(data: bytes, filename: str, content_type: str | None) -> tuple[str, int]:
    """Speech-to-text via Whisper. Returns (transcript, elapsed_ms)."""
    if not data:
        raise AppError("stt_failed", "The recording came through empty - please try again.")
    if len(data) > MAX_AUDIO_BYTES:
        raise AppError("invalid_input", "Audio is too large (max 10 MB).")

    t0 = perf_counter()
    try:
        resp = client().audio.transcriptions.create(
            model=settings.openai_stt_model,
            file=(filename or "audio.webm", data, content_type or "application/octet-stream"),
            # Bias proper-noun spelling; the user may speak English or Arabic.
            prompt="The user is talking to a voice assistant named Sarjy, "
            "in English or Egyptian Arabic.",
        )
    except OpenAIError as exc:
        logger.error("STT failed: %s: %s", type(exc).__name__, exc)
        raise AppError(
            "stt_failed", "I couldn't process that recording - try again or type instead.", 502
        ) from exc
    elapsed_ms = int((perf_counter() - t0) * 1000)

    text = (resp.text or "").strip()
    if not text:
        raise AppError("stt_failed", "I didn't catch any speech in that - please try again.")
    return text, elapsed_ms
