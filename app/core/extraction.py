"""Deterministic memory extraction: a background sweep after every turn.

The conversational model is *asked* to save facts via save_memory, but that is
probabilistic - it sometimes just answers. This sweep is the safety net: a
dedicated, single-purpose pass over the user's message that extracts stable
facts every time. It runs on a worker thread after the reply has already been
sent, so it adds zero latency to the turn. Upserts make double-saving harmless
when the main turn already stored a fact.
"""

import logging
from concurrent.futures import Future, ThreadPoolExecutor

from pydantic import ValidationError

from app.db.engine import open_session
from app.db.repositories import MemoryRepo
from app.schemas.tools import SaveMemoryArgs
from app.services import llm
from app.tools import memory_tools

logger = logging.getLogger(__name__)

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mem-extract")

MIN_TEXT_LEN = 6

EXTRACT_PROMPT = """\
You extract stable personal facts about the user from ONE message, for long-term \
memory: name, age, preferences, favorite things, home city, dietary needs. The \
message may be in English or Arabic. For each fact found, call save_memory once \
(key in English snake_case, value in the user's words). If there are no stable \
facts, reply with the single word: none. Never extract secrets, payment details, \
health information, or one-off situational details."""


def sweep(user_id: str, user_text: str) -> int:
    """Extract and persist facts from one message. Returns facts saved."""
    if len(user_text.strip()) < MIN_TEXT_LEN:
        return 0
    saved = 0
    try:
        msg = llm.chat(
            [
                {"role": "system", "content": EXTRACT_PROMPT},
                {"role": "user", "content": user_text},
            ],
            tools=[memory_tools.SAVE_MEMORY_SPEC],
        )
        if not msg.tool_calls:
            return 0
        db = open_session()
        try:
            repo = MemoryRepo(db)
            for tc in msg.tool_calls:
                if tc.function.name != "save_memory":
                    continue
                try:
                    args = SaveMemoryArgs.model_validate_json(tc.function.arguments)
                except ValidationError as exc:
                    logger.info("extraction sweep skipped invalid fact: %s", exc)
                    continue
                result = memory_tools.save_memory(repo, user_id, args)
                saved += 1 if "saved" in result else 0
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 - the sweep must never break a turn
        logger.warning("extraction sweep failed: %s: %s", type(exc).__name__, exc)
    if saved:
        logger.info("extraction sweep saved %d fact(s)", saved)
    return saved


def submit_sweep(user_id: str, user_text: str) -> Future:
    return _pool.submit(sweep, user_id, user_text)
