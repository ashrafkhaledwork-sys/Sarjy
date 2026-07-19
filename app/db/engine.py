from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


_engine = None
_session_factory: sessionmaker | None = None


def init_db(url: str | None = None) -> None:
    """Create the engine and all tables. Called from app lifespan (and tests)."""
    global _engine, _session_factory
    url = url or settings.database_url
    if url.startswith("sqlite:///") and ":memory:" not in url:
        db_path = Path(url.removeprefix("sqlite:///"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    _engine = create_engine(url, connect_args=connect_args)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)

    from app.db import models  # noqa: F401  (registers tables on Base)

    Base.metadata.create_all(_engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a DB session."""
    if _session_factory is None:  # pragma: no cover - guarded by lifespan
        raise RuntimeError("init_db() was not called")
    db = _session_factory()
    try:
        yield db
    finally:
        db.close()


def db_ping() -> bool:
    from sqlalchemy import text

    if _engine is None:
        return False
    with _engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return True
