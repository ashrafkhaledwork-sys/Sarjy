"""Tool specs + dispatch. The single boundary between the LLM and the world.

Every tool call is parsed with Pydantic; invalid arguments return a structured
error the model can repair from. Phase 7 adds the FSM legality check here.
"""

import json
import logging
from dataclasses import dataclass

from pydantic import ValidationError

from app.db.repositories import MemoryRepo
from app.schemas.tools import DeleteMemoryArgs, SaveMemoryArgs, SearchRestaurantsArgs
from app.tools import memory_tools, places

logger = logging.getLogger(__name__)

SEARCH_RESTAURANTS_SPEC = {
    "type": "function",
    "function": {
        "name": "search_restaurants",
        "description": (
            "Search real restaurants near a location. Present at most 3 options by name. "
            "Only ever mention restaurants returned by this tool; if it errors, say "
            "search is unavailable right now."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "near": {"type": "string", "description": "city, neighborhood, or area"},
                "query": {"type": "string", "description": "cuisine or kind of food"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "required": ["near"],
        },
    },
}


@dataclass
class ToolContext:
    memory_repo: MemoryRepo
    user_id: str
    memories_updated: bool = False


def specs() -> list[dict]:
    return [
        memory_tools.SAVE_MEMORY_SPEC,
        memory_tools.DELETE_MEMORY_SPEC,
        SEARCH_RESTAURANTS_SPEC,
    ]


def dispatch(name: str, raw_args: str, ctx: ToolContext) -> dict:
    """Execute one tool call and return a JSON-able result for the model."""
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError:
        return {"error": "arguments were not valid JSON"}

    try:
        if name == "save_memory":
            result = memory_tools.save_memory(
                ctx.memory_repo, ctx.user_id, SaveMemoryArgs.model_validate(args)
            )
            ctx.memories_updated = ctx.memories_updated or "saved" in result
        elif name == "delete_memory":
            result = memory_tools.delete_memory(
                ctx.memory_repo, ctx.user_id, DeleteMemoryArgs.model_validate(args)
            )
            ctx.memories_updated = ctx.memories_updated or "deleted" in result
        elif name == "search_restaurants":
            parsed = SearchRestaurantsArgs.model_validate(args)
            result = places.search_restaurants(parsed.query, parsed.near, parsed.limit)
        else:
            result = {"error": f"unknown tool: {name}"}
    except ValidationError as exc:
        # One repair round: the model sees exactly which field was wrong.
        result = {"error": f"invalid arguments: {exc.errors()[0]['msg']}"}

    logger.info("tool %s -> %s", name, "error" if "error" in result else "ok")
    return result
