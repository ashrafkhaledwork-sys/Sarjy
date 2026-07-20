"""The booking FSM, tested with zero network and zero LLM.

Every legal transition, every guard, and the persistence/resume path.
A stub search_fn stands in for the Places API.
"""

import uuid
from datetime import date, timedelta

import pytest

from app.db import engine
from app.db.repositories import BookingRepo
from app.workflow.fsm import AFFIRMATION_RE, BookingFSM
from app.workflow.slots import validate_slots

TOMORROW = (date.today() + timedelta(days=1)).isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()

OPTIONS = {
    "restaurants": [
        {"name": "La Trattoria", "address": "El Mara'ashly St"},
        {"name": "Vola Vola", "address": "Zamalek"},
    ]
}

FULL = {"area": "Zamalek", "party_size": 4, "date": TOMORROW, "time": "20:00"}


def ok_search(query, near, limit):
    return {"restaurants": [dict(r) for r in OPTIONS["restaurants"]]}


def failing_search(query, near, limit):
    return {"error": "search_unavailable"}


def empty_search(query, near, limit):
    return {"restaurants": []}


@pytest.fixture()
def repo():
    engine.init_db("sqlite:///:memory:")
    gen = engine.get_db()
    db = next(gen)
    yield BookingRepo(db)
    db.close()


def make_fsm(repo, user_id=None, search=ok_search):
    return BookingFSM(repo, user_id or str(uuid.uuid4()), search_fn=search)


# ---- state machine basics ----------------------------------------------------


class TestTransitions:
    def test_initial_state_is_idle(self, repo):
        assert make_fsm(repo).state == "IDLE"

    def test_first_update_starts_collecting(self, repo):
        fsm = make_fsm(repo)
        result = fsm.apply_update({"party_size": 4})
        assert fsm.state == "COLLECTING"
        assert result["accepted"] == {"party_size": 4}
        assert set(result["missing"]) == {"area", "date", "time"}

    def test_slots_accumulate_across_updates(self, repo):
        fsm = make_fsm(repo)
        fsm.apply_update({"party_size": 4})
        fsm.apply_update({"area": "Zamalek", "cuisine": "italian"})
        assert fsm.booking.slots["party_size"] == 4
        assert fsm.booking.slots["area"] == "Zamalek"
        assert fsm.state == "COLLECTING"

    def test_complete_slots_trigger_search_and_presenting(self, repo):
        fsm = make_fsm(repo)
        result = fsm.apply_update(dict(FULL))
        assert fsm.state == "PRESENTING"
        assert [o["name"] for o in result["options"]] == ["La Trattoria", "Vola Vola"]
        assert fsm.booking.options[0]["name"] == "La Trattoria"

    def test_select_moves_to_confirming(self, repo):
        fsm = make_fsm(repo)
        fsm.apply_update(dict(FULL))
        result = fsm.select_option(1)
        assert fsm.state == "CONFIRMING"
        assert result["selected"] == "La Trattoria"
        assert "La Trattoria" in result["summary"]

    def test_confirm_with_yes_completes(self, repo):
        fsm = make_fsm(repo)
        fsm.apply_update(dict(FULL))
        fsm.select_option(1)
        result = fsm.confirm("yes, book it")
        assert fsm.state == "COMPLETED"
        assert result["booked"] is True

    def test_cancel_from_every_active_state(self, repo):
        for setup in (
            lambda f: f.apply_update({"party_size": 2}),  # COLLECTING
            lambda f: f.apply_update(dict(FULL)),  # PRESENTING
            lambda f: (f.apply_update(dict(FULL)), f.select_option(1)),  # CONFIRMING
        ):
            fsm = make_fsm(repo)
            setup(fsm)
            assert fsm.cancel() == {"cancelled": True}
            assert fsm.state == "CANCELLED"

    def test_new_booking_after_terminal_state(self, repo):
        user = str(uuid.uuid4())
        fsm = make_fsm(repo, user)
        fsm.apply_update(dict(FULL))
        fsm.select_option(2)
        fsm.confirm("yes")
        fsm2 = BookingFSM(repo, user, search_fn=ok_search)
        assert fsm2.state == "IDLE"  # completed booking is not active
        fsm2.apply_update({"party_size": 2})
        assert fsm2.state == "COLLECTING"
        assert fsm2.booking.id != fsm.booking.id


# ---- guards: the deterministic backstops ------------------------------------


class TestGuards:
    def test_confirm_illegal_outside_confirming(self, repo):
        fsm = make_fsm(repo)
        fsm.apply_update({"party_size": 4})
        result = fsm.confirm("yes")
        assert "error" in result
        assert fsm.state == "COLLECTING"

    def test_confirm_without_affirmative_text_refused(self, repo):
        fsm = make_fsm(repo)
        fsm.apply_update(dict(FULL))
        fsm.select_option(1)
        result = fsm.confirm("what about parking there?")
        assert "error" in result
        assert fsm.state == "CONFIRMING"  # state untouched

    def test_double_confirm_cannot_double_book(self, repo):
        fsm = make_fsm(repo)
        fsm.apply_update(dict(FULL))
        fsm.select_option(1)
        fsm.confirm("yes")
        result = fsm.confirm("yes")
        assert "error" in result  # COMPLETED is terminal: confirm is illegal

    def test_select_illegal_in_collecting(self, repo):
        fsm = make_fsm(repo)
        fsm.apply_update({"party_size": 4})
        assert "error" in fsm.select_option(1)

    def test_select_out_of_range(self, repo):
        fsm = make_fsm(repo)
        fsm.apply_update(dict(FULL))
        result = fsm.select_option(5)
        assert "error" in result
        assert fsm.state == "PRESENTING"

    def test_legal_tools_table(self, repo):
        fsm = make_fsm(repo)
        assert fsm.legal_tools() == {"update_booking"}
        fsm.apply_update(dict(FULL))
        assert "select_option" in fsm.legal_tools()
        assert "confirm_booking" not in fsm.legal_tools()
        fsm.select_option(1)
        assert "confirm_booking" in fsm.legal_tools()


# ---- validation & corrections ------------------------------------------------


class TestValidationAndCorrections:
    def test_invalid_values_rejected_with_reasons(self, repo):
        fsm = make_fsm(repo)
        result = fsm.apply_update({"party_size": 250, "date": YESTERDAY, "area": "Zamalek"})
        assert result["accepted"] == {"area": "Zamalek"}
        assert "party_size" in result["rejected"]
        assert "past" in result["rejected"]["date"]
        assert fsm.state == "COLLECTING"

    def test_correction_in_presenting_triggers_research(self, repo):
        calls = []

        def counting_search(query, near, limit):
            calls.append(near)
            return ok_search(query, near, limit)

        fsm = make_fsm(repo, search=counting_search)
        fsm.apply_update(dict(FULL))
        result = fsm.apply_update({"party_size": 6})
        assert fsm.state == "PRESENTING"
        assert fsm.booking.slots["party_size"] == 6
        assert len(calls) == 2  # re-searched with corrected criteria
        assert "options" in result

    def test_correction_in_confirming_clears_selection(self, repo):
        fsm = make_fsm(repo)
        fsm.apply_update(dict(FULL))
        fsm.select_option(1)
        fsm.apply_update({"time": "21:00"})
        assert fsm.booking.restaurant is None  # stale choice invalidated
        assert fsm.state == "PRESENTING"

    def test_search_failure_stays_collecting(self, repo):
        fsm = make_fsm(repo, search=failing_search)
        result = fsm.apply_update(dict(FULL))
        assert result["error"] == "search_unavailable"
        assert fsm.state == "COLLECTING"  # retryable, nothing lost

    def test_zero_results_guides_user(self, repo):
        fsm = make_fsm(repo, search=empty_search)
        result = fsm.apply_update(dict(FULL))
        assert result["restaurants"] == []
        assert fsm.state == "COLLECTING"


# ---- persistence / resume ----------------------------------------------------


class TestResume:
    def test_state_survives_new_fsm_instance(self, repo):
        user = str(uuid.uuid4())
        fsm = make_fsm(repo, user)
        fsm.apply_update({"party_size": 4, "area": "Zamalek"})

        resumed = BookingFSM(repo, user, search_fn=ok_search)
        assert resumed.state == "COLLECTING"
        assert resumed.booking.slots == {"party_size": 4, "area": "Zamalek"}
        assert resumed.booking.id == fsm.booking.id

    def test_confirming_state_survives_resume(self, repo):
        user = str(uuid.uuid4())
        fsm = make_fsm(repo, user)
        fsm.apply_update(dict(FULL))
        fsm.select_option(2)

        resumed = BookingFSM(repo, user, search_fn=ok_search)
        assert resumed.state == "CONFIRMING"
        assert resumed.booking.restaurant["name"] == "Vola Vola"
        result = resumed.confirm("yes please")
        assert result["booked"] is True


# ---- slot validators & affirmation ------------------------------------------


class TestValidators:
    def test_time_normalized(self):
        accepted, _ = validate_slots({"time": "8:05"}, date.today())
        assert accepted["time"] == "08:05"

    def test_bad_time_rejected(self):
        _, rejected = validate_slots({"time": "quarter past eight"}, date.today())
        assert "time" in rejected

    def test_today_is_valid_date(self):
        accepted, rejected = validate_slots({"date": date.today().isoformat()}, date.today())
        assert accepted["date"] == date.today().isoformat()
        assert rejected == {}

    def test_affirmations(self):
        for text in ("yes", "Yeah go ahead", "book it!", "ok sounds good", "Confirm."):
            assert AFFIRMATION_RE.search(text), text
        for text in ("no", "wait", "hmm let me think", "change the time"):
            assert not AFFIRMATION_RE.search(text), text

    def test_arabic_affirmations(self):
        for text in ("نعم", "كله تمام نعم", "أيوة احجز", "ماشي", "تمام يلا", "أكيد"):
            assert AFFIRMATION_RE.search(text), text
        for text in ("لا", "مش تمام", "لا ماشي غير كده", "استنى شوية"):
            assert not AFFIRMATION_RE.search(text), text
