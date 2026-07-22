import base64
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from time import perf_counter

from app.core import extraction
from app.core.prompts import build_system_prompt, format_memories, format_workflow
from app.db.repositories import BookingRepo, ConversationRepo, MemoryRepo
from app.services import llm, moderation
from app.tools import registry
from app.workflow.fsm import BookingFSM

FALLBACK_REPLY = "Sorry, I didn't catch that - could you say it again?"
REFUSAL_REPLY_EN = (
    "I can't help with that. I'm happy to chat, remember things for you, "
    "or plan your next dinner out."
)
REFUSAL_REPLY_AR = "معرفش أساعدك في ده، بس أقدر أدردش معاك، أفتكر حاجات عنك، أو أظبطلك عشا برة."
_ARABIC_RE = re.compile(r"[؀-ۿ]")


def refusal_reply(user_text: str) -> str:
    return REFUSAL_REPLY_AR if _ARABIC_RE.search(user_text) else REFUSAL_REPLY_EN
MAX_TOOL_ROUNDS = 4

# Moderation runs concurrently with the first LLM round (hides its latency).
# Its verdict is checked BEFORE any tool executes, so side effects stay gated.
_moderation_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="moderation")


@dataclass
class TurnResult:
    reply_text: str
    llm_ms: int
    tool_ms: int
    memories_updated: bool
    workflow: dict = field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0


def run_text_turn(
    repo: ConversationRepo,
    memory_repo: MemoryRepo,
    booking_repo: BookingRepo,
    user_id: str,
    session_id: str,
    user_text: str,
    image: tuple[bytes, str] | None = None,
) -> TurnResult:
    """One conversation turn: persist input, build context (memories + history +
    workflow state), run the LLM with tools until a final reply, persist it.

    An attached image rides along on the current turn only: history persists a
    text marker, so old images never bloat the context window."""
    repo.touch_user(user_id)
    repo.get_or_create_session(session_id, user_id)
    first_message_of_session = repo.recent_messages(session_id, limit=1) == []
    stored_text = user_text if image is None else f"{user_text} [image attached]".strip()
    repo.add_message(session_id, "user", stored_text)

    fsm = BookingFSM(booking_repo, user_id)
    moderation_future = _moderation_pool.submit(moderation.flagged, user_text)
    memories = memory_repo.list_for_user(user_id)
    today = date.today()
    system = build_system_prompt(
        memories_block=format_memories(memories),
        workflow_block=format_workflow(fsm.public_state(), resuming=first_message_of_session),
        today_line=f"Today is {today.strftime('%A')}, {today.isoformat()}.",
    )
    history = [{"role": m.role, "content": m.content} for m in repo.recent_messages(session_id)]
    if image is not None and history:
        img_bytes, mime = image
        data_url = f"data:{mime};base64,{base64.b64encode(img_bytes).decode('ascii')}"
        history[-1] = {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text or "Describe what you see."},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }
    messages: list[dict] = [{"role": "system", "content": system}, *history]

    ctx = registry.ToolContext(
        memory_repo=memory_repo, user_id=user_id, fsm=fsm, user_text=user_text
    )
    llm_ms = 0
    tool_ms = 0
    tokens_in = 0
    tokens_out = 0

    assistant = None
    moderation_checked = False
    for _ in range(MAX_TOOL_ROUNDS):
        t0 = perf_counter()
        assistant = llm.chat(messages, tools=registry.specs())
        llm_ms += int((perf_counter() - t0) * 1000)
        tokens_in += assistant.usage_in
        tokens_out += assistant.usage_out

        if not moderation_checked:
            # Verdict gates everything downstream: tools and the final reply.
            is_flagged, _ = moderation_future.result()
            moderation_checked = True
            if is_flagged:
                refusal = refusal_reply(user_text)
                repo.add_message(session_id, "assistant", refusal)
                return TurnResult(
                    reply_text=refusal,
                    llm_ms=llm_ms,
                    tool_ms=0,
                    memories_updated=False,
                    workflow=fsm.public_state(),
                )

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

    # Safety net: deterministic fact extraction, off the critical path.
    extraction.submit_sweep(user_id, user_text)

    return TurnResult(
        reply_text=reply,
        llm_ms=llm_ms,
        tool_ms=tool_ms,
        memories_updated=ctx.memories_updated,
        workflow=fsm.public_state(),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
