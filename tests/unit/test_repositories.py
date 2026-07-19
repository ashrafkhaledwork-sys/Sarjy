import uuid

import pytest

from app.db import engine
from app.db.repositories import ConversationRepo


@pytest.fixture()
def repo():
    engine.init_db("sqlite:///:memory:")
    gen = engine.get_db()
    db = next(gen)
    yield ConversationRepo(db)
    db.close()


def _ids():
    return str(uuid.uuid4()), str(uuid.uuid4())


def test_touch_user_creates_then_updates(repo):
    user_id, _ = _ids()
    u1 = repo.touch_user(user_id)
    u2 = repo.touch_user(user_id)
    assert u1.id == u2.id == user_id
    assert u2.last_seen_at >= u1.created_at


def test_messages_persist_in_order(repo):
    user_id, session_id = _ids()
    repo.touch_user(user_id)
    repo.get_or_create_session(session_id, user_id)
    repo.add_message(session_id, "user", "one")
    repo.add_message(session_id, "assistant", "two")
    repo.add_message(session_id, "user", "three")

    msgs = repo.recent_messages(session_id)
    assert [m.content for m in msgs] == ["one", "two", "three"]
    assert [m.role for m in msgs] == ["user", "assistant", "user"]


def test_history_window_keeps_last_n(repo):
    user_id, session_id = _ids()
    repo.touch_user(user_id)
    repo.get_or_create_session(session_id, user_id)
    for i in range(20):
        repo.add_message(session_id, "user", f"msg-{i}")

    msgs = repo.recent_messages(session_id, limit=12)
    assert len(msgs) == 12
    assert msgs[0].content == "msg-8"  # oldest retained
    assert msgs[-1].content == "msg-19"  # newest last


def test_sessions_are_isolated(repo):
    user_id, s1 = _ids()
    _, s2 = _ids()
    repo.touch_user(user_id)
    repo.get_or_create_session(s1, user_id)
    repo.get_or_create_session(s2, user_id)
    repo.add_message(s1, "user", "in session one")

    assert repo.recent_messages(s2) == []
