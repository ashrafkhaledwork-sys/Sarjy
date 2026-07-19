"""save_memory / delete_memory: the LLM's only path to long-term memory.

Defense in depth: the system prompt tells the model not to store sensitive
data, and this server-side guard rejects it even if the model tries.
"""

import re

from app.db.repositories import MemoryRepo
from app.schemas.tools import DeleteMemoryArgs, SaveMemoryArgs

SAVE_MEMORY_SPEC = {
    "type": "function",
    "function": {
        "name": "save_memory",
        "description": (
            "Save one stable personal fact about the user for future sessions "
            "(name, preferences, city). Never for secrets, payment data, health, "
            "or one-off details."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ["identity", "preference", "context"]},
                "key": {
                    "type": "string",
                    "description": "snake_case fact name, e.g. favorite_color, name, home_city",
                },
                "value": {"type": "string"},
            },
            "required": ["category", "key", "value"],
        },
    },
}

DELETE_MEMORY_SPEC = {
    "type": "function",
    "function": {
        "name": "delete_memory",
        "description": "Forget a stored fact when the user asks you to.",
        "parameters": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
}

_SENSITIVE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "looks like a payment card number"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "looks like a national ID number"),
    (re.compile(r"(?i)\b(password|passcode|passphrase|cvv|pin)\b"), "looks like a credential"),
    (re.compile(r"(?i)\bsk-[a-z0-9_-]{8,}"), "looks like an API key"),
]


def sensitive_reason(text: str) -> str | None:
    for pattern, reason in _SENSITIVE_PATTERNS:
        if pattern.search(text):
            return reason
    return None


def save_memory(repo: MemoryRepo, user_id: str, args: SaveMemoryArgs) -> dict:
    reason = sensitive_reason(f"{args.key} {args.value}")
    if reason:
        return {"error": f"refused: {reason}; sensitive data is never stored"}
    repo.upsert(user_id, args.category, args.key, args.value)
    return {"saved": args.key}


def delete_memory(repo: MemoryRepo, user_id: str, args: DeleteMemoryArgs) -> dict:
    deleted = repo.delete(user_id, args.key)
    return {"deleted": args.key} if deleted else {"error": f"no memory named {args.key}"}
