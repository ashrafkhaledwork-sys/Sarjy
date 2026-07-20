"""Input guardrail: OpenAI moderation (free) screens user text before the LLM.

Fail-open by design: if moderation itself is unavailable we log and continue -
for this product, availability beats blocking, and the prompt-level policy
plus the FSM guards still stand behind it.
"""

import logging
from time import perf_counter

from openai import OpenAIError

from app.services.llm import client

logger = logging.getLogger(__name__)


def flagged(text: str) -> tuple[bool, int]:
    """Returns (is_flagged, elapsed_ms)."""
    t0 = perf_counter()
    try:
        # No retries: this guardrail is fail-open, so a fast miss beats a slow one.
        resp = client().with_options(max_retries=0).moderations.create(
            model="omni-moderation-latest", input=text[:4000]
        )
    except OpenAIError as exc:
        logger.warning("moderation unavailable (fail-open): %s", exc)
        return False, int((perf_counter() - t0) * 1000)
    elapsed = int((perf_counter() - t0) * 1000)
    is_flagged = bool(resp.results[0].flagged)
    if is_flagged:
        categories = [k for k, v in resp.results[0].categories.model_dump().items() if v]
        logger.info("input flagged by moderation: %s", categories)
    return is_flagged, elapsed
