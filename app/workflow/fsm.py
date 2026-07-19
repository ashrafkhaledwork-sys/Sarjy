"""The booking finite-state machine - the deep-dive core.

The LLM proposes tool calls; this FSM disposes. It owns the state, the legal
transitions, and the guards. Notably:

- Tool legality is a per-state table, enforced before any tool runs.
- confirm_booking succeeds only in CONFIRMING *and* only when the user's own
  literal words this turn were affirmative - a prompt injection or model
  hallucination cannot book anything.
- The restaurant search runs from FSM-validated slots (injected as search_fn,
  so the whole machine unit-tests without any network).

States: IDLE -> COLLECTING -> PRESENTING -> CONFIRMING -> COMPLETED
                    ^______________|_____________|            CANCELLED
"""

import re
from collections.abc import Callable
from datetime import date, datetime

from app.db.models import Booking
from app.db.repositories import ACTIVE_BOOKING_STATES, BookingRepo
from app.tools import places
from app.workflow.slots import missing_slots, validate_slots

AFFIRMATION_RE = re.compile(
    r"(?i)\b(yes|yeah|yep|sure|confirm|confirmed|book it|go ahead|do it|okay|ok|"
    r"sounds good|correct|please do|that works)\b"
)

TERMINAL_STATES = ("COMPLETED", "CANCELLED")

# state -> booking tools the model is allowed to call
LEGAL_TOOLS: dict[str, frozenset[str]] = {
    "IDLE": frozenset({"update_booking"}),
    "COLLECTING": frozenset({"update_booking", "cancel_booking"}),
    "PRESENTING": frozenset({"update_booking", "select_option", "cancel_booking"}),
    "CONFIRMING": frozenset({"update_booking", "confirm_booking", "cancel_booking"}),
    # terminal states: update_booking starts a fresh booking
    "COMPLETED": frozenset({"update_booking"}),
    "CANCELLED": frozenset({"update_booking"}),
}

SEARCH_LIMIT = 3


def _summary(booking: Booking) -> str:
    s = booking.slots
    name = (booking.restaurant or {}).get("name", "the selected restaurant")
    return (
        f"{name} for {s.get('party_size')} people on {s.get('date')} at {s.get('time')}"
        f" in {s.get('area')}"
    )


class BookingFSM:
    def __init__(
        self,
        repo: BookingRepo,
        user_id: str,
        search_fn: Callable[[str, str, int], dict] = places.search_restaurants,
    ):
        self.repo = repo
        self.user_id = user_id
        self.search_fn = search_fn
        self.booking: Booking | None = repo.active_for_user(user_id)

    # ---- state introspection -------------------------------------------------

    @property
    def state(self) -> str:
        return self.booking.status if self.booking else "IDLE"

    @property
    def has_active_booking(self) -> bool:
        return self.state in ACTIVE_BOOKING_STATES

    def legal_tools(self) -> frozenset[str]:
        return LEGAL_TOOLS[self.state]

    def illegal_result(self, tool: str) -> dict:
        return {
            "error": (
                f"{tool} is not allowed while the booking is in state {self.state}. "
                f"Allowed now: {', '.join(sorted(self.legal_tools()))}."
            )
        }

    def public_state(self) -> dict:
        if self.booking is None:
            return {"status": "IDLE", "slots": {}, "missing": [], "options": None}
        return {
            "status": self.booking.status,
            "slots": dict(self.booking.slots),
            "missing": missing_slots(self.booking.slots) if self.has_active_booking else [],
            "options": [
                {"name": o.get("name", ""), "address": o.get("address", "")}
                for o in (self.booking.options or [])
            ]
            if self.booking.status == "PRESENTING"
            else None,
            "selected": (self.booking.restaurant or {}).get("name")
            if self.booking.status in ("CONFIRMING", "COMPLETED")
            else None,
        }

    # ---- transitions ---------------------------------------------------------

    def apply_update(self, fields: dict) -> dict:
        accepted, rejected = validate_slots(fields, date.today(), now=datetime.now())

        if not accepted and not rejected:
            return {"error": "no usable booking details were provided"}

        if self.booking is None or self.booking.status in TERMINAL_STATES:
            self.booking = self.repo.create(self.user_id)

        # corrections invalidate any previously chosen restaurant
        if accepted:
            self.booking.slots = {**self.booking.slots, **accepted}
            self.booking.restaurant = None

        missing = missing_slots(self.booking.slots)
        result: dict = {"accepted": accepted}
        if rejected:
            result["rejected"] = rejected

        if missing:
            self.booking.status = "COLLECTING"
            self.booking.options = None
            result["missing"] = missing
        else:
            result.update(self._search_and_present())

        self.repo.save(self.booking)
        return result

    def _search_and_present(self) -> dict:
        """All required slots present: run the search from FSM-owned values."""
        slots = self.booking.slots
        query = slots.get("cuisine") or "restaurant"
        search = self.search_fn(query, slots["area"], SEARCH_LIMIT)

        if "error" in search:
            self.booking.status = "COLLECTING"  # complete but unsearched; retry is natural
            return {"error": "search_unavailable", "note": "offer to try the search again"}

        restaurants = search["restaurants"]
        if not restaurants:
            self.booking.status = "COLLECTING"
            return {
                "restaurants": [],
                "note": "no results for these criteria; suggest a different area or cuisine",
            }

        self.booking.options = restaurants
        self.booking.status = "PRESENTING"
        return {
            "options": [
                {"n": i + 1, "name": r["name"], "address": r.get("address", "")}
                for i, r in enumerate(restaurants)
            ],
            "note": "present these briefly and ask the user to pick one",
        }

    def select_option(self, n: int) -> dict:
        if self.state != "PRESENTING":
            return self.illegal_result("select_option")
        options = self.booking.options or []
        if not 1 <= n <= len(options):
            return {"error": f"option {n} does not exist; there are {len(options)} options"}
        self.booking.restaurant = options[n - 1]
        self.booking.status = "CONFIRMING"
        self.repo.save(self.booking)
        return {
            "selected": options[n - 1]["name"],
            "summary": _summary(self.booking),
            "note": "read this summary back and ask for an explicit yes before confirming",
        }

    def confirm(self, user_text: str) -> dict:
        if self.state != "CONFIRMING":
            return self.illegal_result("confirm_booking")
        if not AFFIRMATION_RE.search(user_text):
            return {
                "error": (
                    "the user has not clearly said yes in their last message - "
                    "ask for explicit confirmation first"
                )
            }
        self.booking.status = "COMPLETED"
        self.repo.save(self.booking)
        return {"booked": True, "summary": _summary(self.booking)}

    def cancel(self) -> dict:
        if not self.has_active_booking:
            return self.illegal_result("cancel_booking")
        self.booking.status = "CANCELLED"
        self.repo.save(self.booking)
        return {"cancelled": True}
