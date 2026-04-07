"""Database engine and session management.

Provides the SQLAlchemy engine, declarative base, session factory,
and a ``get_db`` context manager for obtaining scoped sessions.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine
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

    return create_engine(db_url)


def get_session_factory(url: str | None = None) -> sessionmaker[Session]:
    """Return a ``sessionmaker`` bound to the engine for *url*."""
    engine = get_engine(url)
    return sessionmaker(bind=engine)


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
