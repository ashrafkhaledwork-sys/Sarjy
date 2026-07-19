import logging
from time import perf_counter

from openai import OpenAIError

from app.config import settings
from app.services.llm import client

logger = logging.getLogger(__name__)


def synthesize(text: str) -> tuple[bytes | None, int]:
    """Text-to-speech. Returns (mp3_bytes, elapsed_ms); (None, ms) on failure.

    TTS failure must never fail the turn - the client falls back to
    browser speechSynthesis when audio is missing.
    """
    t0 = perf_counter()
    try:
        resp = client().audio.speech.create(
            model=settings.openai_tts_model,
            voice=settings.openai_tts_voice,
            input=text,
            response_format="mp3",
        )
        audio = resp.read()
    except OpenAIError as exc:
        logger.error("TTS failed (degrading to text): %s: %s", type(exc).__name__, exc)
        return None, int((perf_counter() - t0) * 1000)
    return audio, int((perf_counter() - t0) * 1000)
