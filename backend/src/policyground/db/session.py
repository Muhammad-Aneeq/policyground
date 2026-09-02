"""Engine and session management for SQLite (dev) and Postgres (prod).

Spec 00 A1 specifies "SQLAlchemy (SQLite dev / Postgres prod)". One model set covers both; the only
dialect-aware code is here, and it is confined to two SQLite quirks that would otherwise produce
confusing failures during a demo.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from policyground.config import Settings, get_settings, repo_root
from policyground.db.models import Base


def _resolve_sqlite_path(url: str) -> str:
    """Make a relative SQLite path absolute against the repo root.

    ``sqlite:///data/policyground.db`` is relative to the *working directory*, so the API started
    from ``backend/`` and the CLI run from the repo root would silently use two different databases
    — and the admin dashboard would show an empty unanswered log while the chat was busily writing
    to it.
    """
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return url

    raw = url[len(prefix) :]
    if raw.startswith(":memory:") or Path(raw).is_absolute():
        return url

    absolute = (repo_root() / raw).resolve()
    absolute.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}{absolute.as_posix()}"


def create_db_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    url = _resolve_sqlite_path(settings.database_url)

    is_sqlite = url.startswith("sqlite")
    engine = create_engine(
        url,
        # FastAPI serves requests on a threadpool; SQLite's default same-thread check would reject
        # a connection reused across threads.
        connect_args={"check_same_thread": False} if is_sqlite else {},
        pool_pre_ping=not is_sqlite,
        future=True,
    )

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            # SQLite ignores FOREIGN KEY constraints unless asked not to. Without this, the
            # cascade from `queries` to `answers` silently does nothing and orphan rows accumulate
            # — on Postgres the same code would behave correctly, which is the worst kind of
            # difference between dev and prod.
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_db_engine()


def init_db(engine: Engine | None = None) -> Engine:
    """Create tables if absent.

    ``create_all`` rather than migrations: v1 has no upgrade path to preserve, and a schema change
    is handled by deleting a rebuildable dev database. Real migrations belong with the first real
    deployment, and that is called out in the runbook rather than pretended away here.
    """
    engine = engine or get_engine()
    Base.metadata.create_all(engine)
    return engine


def session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=engine or get_engine(), expire_on_commit=False, future=True)


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on failure, always close."""
    factory = session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine_cache() -> None:
    """Drop the cached engine — used by tests that point at a temporary database."""
    get_engine.cache_clear()
