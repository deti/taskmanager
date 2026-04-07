"""Database engine and session management.

Provides the SQLAlchemy engine, declarative base, session factory,
and a ``get_db`` context manager for obtaining scoped sessions.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from taskmanager.settings import get_settings


class Base(DeclarativeBase):
    """Declarative base class for all ORM models."""


def _resolve_db_url(url: str) -> str:
    """Expand ``~`` in sqlite file paths so the engine can find the directory."""
    prefix = "sqlite:///"
    if url.startswith(prefix):
        file_path = url[len(prefix) :]
        resolved = str(Path(file_path).expanduser())
        return f"{prefix}{resolved}"
    return url


def get_engine(url: str | None = None) -> Engine:
    """Create and return a SQLAlchemy engine.

    Parameters
    ----------
    url:
        Database URL.  Defaults to ``get_settings().db_url``.
    """
    db_url = url or get_settings().db_url
    db_url = _resolve_db_url(db_url)

    # Ensure the parent directory exists for sqlite file databases.
    prefix = "sqlite:///"
    if db_url.startswith(prefix):
        db_path = db_url[len(prefix) :]
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(db_url)

    # Enable foreign key constraints for SQLite.
    if db_url.startswith(prefix):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn: Any, connection_record: Any) -> None:  # noqa: ARG001
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def get_session_factory(url: str | None = None) -> sessionmaker[Session]:
    """Return a ``sessionmaker`` bound to the engine for *url*."""
    engine = get_engine(url)
    return sessionmaker(bind=engine)


def check_db_connection(url: str | None = None) -> bool:
    """Check if database connection is available.

    Used by health check endpoints to verify DB connectivity without raising exceptions.
    Always returns a boolean and never propagates exceptions to the caller.

    Parameters
    ----------
    url:
        Optional database URL. If None, uses default from settings.

    Returns
    -------
    bool:
        True if connection succeeds, False if any exception occurs.
    """
    try:
        engine = get_engine(url)
        with engine.connect():
            return True
    except Exception:
        return False


@contextmanager
def get_db(url: str | None = None) -> Iterator[Session]:
    """Yield a SQLAlchemy session and ensure it is closed on exit.

    Usage::

        with get_db() as session:
            session.execute(...)
    """
    factory = get_session_factory(url)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
