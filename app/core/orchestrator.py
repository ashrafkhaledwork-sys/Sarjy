from dataclasses import dataclass
from time import perf_counter

from app.core.prompts import build_system_prompt
from app.db.repositories import ConversationRepo
from app.services import llm

FALLBACK_REPLY = "Sorry, I didn't catch that - could you say it again?"


@dataclass
class TurnResult:
    reply_text: str
    llm_ms: int


def run_text_turn(
    repo: ConversationRepo, user_id: str, session_id: str, user_text: str
) -> TurnResult:
    """One conversation turn: persist input, build context, call the LLM,
    persist the reply. Tools and workflow state plug in here in later phases."""
    repo.touch_user(user_id)
    repo.get_or_create_session(session_id, user_id)
    repo.add_message(session_id, "user", user_text)

    history = [{"role": m.role, "content": m.content} for m in repo.recent_messages(session_id)]
    messages = [{"role": "system", "content": build_system_prompt()}, *history]

    t0 = perf_counter()
    assistant = llm.chat(messages)
    llm_ms = int((perf_counter() - t0) * 1000)

    reply = (assistant.content or "").strip() or FALLBACK_REPLY
    repo.add_message(session_id, "assistant", reply)
    return TurnResult(reply_text=reply, llm_ms=llm_ms)
