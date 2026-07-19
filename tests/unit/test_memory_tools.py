import uuid

import pytest
from pydantic import ValidationError

from app.db import engine
from app.db.repositories import MemoryRepo
from app.schemas.tools import SaveMemoryArgs
from app.tools.memory_tools import save_memory, sensitive_reason


@pytest.fixture()
def repo():
    engine.init_db("sqlite:///:memory:")
    gen = engine.get_db()
    db = next(gen)
    yield MemoryRepo(db)
    db.close()


USER = str(uuid.uuid4())


class TestSensitiveGuard:
    def test_card_number_blocked(self):
        assert sensitive_reason("my card is 4111 1111 1111 1111") is not None

    def test_ssn_like_blocked(self):
        assert sensitive_reason("ssn 123-45-6789") is not None

    def test_password_keyword_blocked(self):
        assert sensitive_reason("my password is hunter2") is not None

    def test_api_key_blocked(self):
        assert sensitive_reason("key sk-abc123def456ghi") is not None

    def test_normal_facts_allowed(self):
        assert sensitive_reason("favorite color blue") is None
        assert sensitive_reason("lives in Cairo, party of 4 usually") is None


class TestSaveMemoryArgs:
    def test_key_normalized_to_snake_case(self):
        args = SaveMemoryArgs(category="preference", key="Favorite Color", value="blue")
        assert args.key == "favorite_color"

    def test_bad_category_rejected(self):
        with pytest.raises(ValidationError):
            SaveMemoryArgs(category="secrets", key="x", value="y")

    def test_empty_value_rejected(self):
        with pytest.raises(ValidationError):
            SaveMemoryArgs(category="identity", key="name", value="")


class TestMemoryRepo:
    def test_upsert_newest_wins(self, repo):
        repo.upsert(USER, "preference", "favorite_color", "blue")
        repo.upsert(USER, "preference", "favorite_color", "green")
        memories = repo.list_for_user(USER)
        assert len(memories) == 1
        assert memories[0].value == "green"

    def test_delete(self, repo):
        repo.upsert(USER, "identity", "name", "Ashraf")
        assert repo.delete(USER, "name") is True
        assert repo.delete(USER, "name") is False
        assert repo.list_for_user(USER) == []

    def test_users_isolated(self, repo):
        other = str(uuid.uuid4())
        repo.upsert(USER, "preference", "favorite_color", "blue")
        assert repo.list_for_user(other) == []

    def test_sensitive_value_refused_at_tool_level(self, repo):
        args = SaveMemoryArgs(category="context", key="note", value="cvv is 123")
        result = save_memory(repo, USER, args)
        assert "error" in result
        assert repo.list_for_user(USER) == []
