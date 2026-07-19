"""Slot definitions and per-field validation for the booking workflow.

Validation is per-field on purpose: one bad value ("party of 250") must not
discard the good values extracted in the same turn. The FSM applies what is
valid and tells the model exactly what was rejected and why.
"""

from datetime import date, datetime, time

REQUIRED_SLOTS = ("area", "party_size", "date", "time")
OPTIONAL_SLOTS = ("cuisine",)

MAX_PARTY = 20


def _validate_area(value) -> str:
    text = str(value).strip()
    if len(text) < 2:
        raise ValueError("area must name a real place")
    return text[:120]


def _validate_cuisine(value) -> str:
    return str(value).strip()[:80]


def _validate_party_size(value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("party_size must be a number") from exc
    if not 1 <= n <= MAX_PARTY:
        raise ValueError(f"party_size must be between 1 and {MAX_PARTY}")
    return n


def _validate_date(value, today: date) -> str:
    try:
        parsed = date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError("date must be ISO format YYYY-MM-DD") from exc
    if parsed < today:
        raise ValueError(f"{parsed.isoformat()} is in the past (today is {today.isoformat()})")
    return parsed.isoformat()


def _validate_time(value) -> str:
    parts = str(value).strip().split(":")
    try:
        if len(parts) != 2:
            raise ValueError
        parsed = time(int(parts[0]), int(parts[1]))  # accepts "8:05" and "20:00"
    except (ValueError, TypeError) as exc:
        raise ValueError("time must be 24h format HH:MM") from exc
    return parsed.strftime("%H:%M")


def validate_slots(
    fields: dict, today: date, now: datetime | None = None
) -> tuple[dict, dict]:
    """Returns (accepted, rejected). rejected maps field -> human reason."""
    accepted: dict = {}
    rejected: dict = {}
    validators = {
        "area": _validate_area,
        "cuisine": _validate_cuisine,
        "party_size": _validate_party_size,
        "date": lambda v: _validate_date(v, today),
        "time": _validate_time,
    }
    for field, value in fields.items():
        if value is None or field not in validators:
            continue
        try:
            accepted[field] = validators[field](value)
        except ValueError as exc:
            rejected[field] = str(exc)

    # cross-field check: a today-booking must not be in the past
    if now is not None and accepted.get("date") == today.isoformat() and "time" in accepted:
        slot_dt = datetime.combine(today, time.fromisoformat(accepted["time"]))
        if slot_dt < now.replace(tzinfo=None):
            rejected["time"] = f"{accepted['time']} today is already in the past"
            del accepted["time"]

    return accepted, rejected


def missing_slots(slots: dict) -> list[str]:
    return [s for s in REQUIRED_SLOTS if not slots.get(s)]
