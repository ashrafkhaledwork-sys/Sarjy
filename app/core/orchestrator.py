import json
from dataclasses import dataclass
from time import perf_counter

from app.core.prompts import build_system_prompt, format_memories
from app.db.repositories import ConversationRepo, MemoryRepo
from app.services import llm
from app.tools import registry

FALLBACK_REPLY = "Sorry, I didn't catch that - could you say it again?"
MAX_TOOL_ROUNDS = 3


@dataclass
class TurnResult:
    reply_text: str
    llm_ms: int
    tool_ms: int
    memories_updated: bool


def run_text_turn(
    repo: ConversationRepo,
    memory_repo: MemoryRepo,
    user_id: str,
    session_id: str,
    user_text: str,
) -> TurnResult:
    """One conversation turn: persist input, build context (memories + history),
    run the LLM with tools until it produces a final reply, persist it."""
    repo.touch_user(user_id)
    repo.get_or_create_session(session_id, user_id)
    repo.add_message(session_id, "user", user_text)

    memories = memory_repo.list_for_user(user_id)
    system = build_system_prompt(memories_block=format_memories(memories))
    history = [{"role": m.role, "content": m.content} for m in repo.recent_messages(session_id)]
    messages: list[dict] = [{"role": "system", "content": system}, *history]

    ctx = registry.ToolContext(memory_repo=memory_repo, user_id=user_id)
    llm_ms = 0
    tool_ms = 0

    assistant = None
    for _ in range(MAX_TOOL_ROUNDS):
        t0 = perf_counter()
        assistant = llm.chat(messages, tools=registry.specs())
        llm_ms += int((perf_counter() - t0) * 1000)
        if not assistant.tool_calls:
            break

        messages.append(
            {
                "role": "assistant",
                "content": assistant.content,
                "tool_calls": [tc.model_dump() for tc in assistant.tool_calls],
            }
        )
        for tc in assistant.tool_calls:
            t1 = perf_counter()
            result = registry.dispatch(tc.function.name, tc.function.arguments, ctx)
            tool_ms += int((perf_counter() - t1) * 1000)
            messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)}
            )

    reply = (assistant.content or "").strip() if assistant else ""
    reply = reply or FALLBACK_REPLY
    repo.add_message(session_id, "assistant", reply)
    return TurnResult(
        reply_text=reply,
        llm_ms=llm_ms,
        tool_ms=tool_ms,
        memories_updated=ctx.memories_updated,
    )
