"""Tool specs + dispatch. The single boundary between the LLM and the world.

Every tool call is parsed with Pydantic; invalid arguments return a structured
error the model can repair from. Phase 7 adds the FSM legality check here.
"""

import json
import logging
from dataclasses import dataclass

from pydantic import ValidationError

from app.db.repositories import MemoryRepo
from app.schemas.tools import (
    DeleteMemoryArgs,
    SaveMemoryArgs,
    SearchRestaurantsArgs,
    SelectOptionArgs,
    UpdateBookingArgs,
)
from app.tools import memory_tools, places
from app.workflow.fsm import BookingFSM

logger = logging.getLogger(__name__)

BOOKING_TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "update_booking",
            "description": (
                "Start or update a restaurant booking with details the user just gave. "
                "Convert dates to YYYY-MM-DD and times to 24h HH:MM using today's date "
                "from the system message. Only pass values the user actually stated."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cuisine": {"type": "string"},
                    "area": {"type": "string", "description": "neighborhood or city"},
                    "party_size": {"type": "integer"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "time": {"type": "string", "description": "24h HH:MM"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "select_option",
            "description": "The user picked one of the presented restaurant options (1-based).",
            "parameters": {
                "type": "object",
                "properties": {"n": {"type": "integer", "minimum": 1}},
                "required": ["n"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_booking",
            "description": (
                "Finalize the booking. Call ONLY after reading the summary back and the "
                "user explicitly said yes."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_booking",
            "description": "Cancel the booking in progress at the user's request.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

BOOKING_TOOLS = {"update_booking", "select_option", "confirm_booking", "cancel_booking"}

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
    fsm: BookingFSM | None = None
    user_text: str = ""
    memories_updated: bool = False


def specs() -> list[dict]:
    return [
        memory_tools.SAVE_MEMORY_SPEC,
        memory_tools.DELETE_MEMORY_SPEC,
        SEARCH_RESTAURANTS_SPEC,
        *BOOKING_TOOL_SPECS,
    ]


def dispatch(name: str, raw_args: str, ctx: ToolContext) -> dict:
    """Execute one tool call and return a JSON-able result for the model."""
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError:
        return {"error": "arguments were not valid JSON"}

    # Deterministic legality gate: the FSM's per-state table decides what the
    # model may do - before any tool logic runs.
    if ctx.fsm is not None:
        if name in BOOKING_TOOLS and name not in ctx.fsm.legal_tools():
            logger.info("tool %s blocked: illegal in state %s", name, ctx.fsm.state)
            return ctx.fsm.illegal_result(name)
        if name == "search_restaurants" and ctx.fsm.has_active_booking:
            return {
                "error": (
                    "a booking is in progress - use update_booking; the search runs "
                    "automatically once the details are complete"
                )
            }

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
        elif name == "update_booking":
            result = ctx.fsm.apply_update(UpdateBookingArgs.model_validate(args).provided())
        elif name == "select_option":
            result = ctx.fsm.select_option(SelectOptionArgs.model_validate(args).n)
        elif name == "confirm_booking":
            result = ctx.fsm.confirm(ctx.user_text)
        elif name == "cancel_booking":
            result = ctx.fsm.cancel()
        else:
            result = {"error": f"unknown tool: {name}"}
    except ValidationError as exc:
        # One repair round: the model sees exactly which field was wrong.
        result = {"error": f"invalid arguments: {exc.errors()[0]['msg']}"}

    logger.info("tool %s -> %s", name, "error" if "error" in result else "ok")
    return result
