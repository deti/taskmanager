"""Database engine and session management for Task Manager.

Provides the SQLAlchemy engine, session factory, and a ``get_db()``
context manager / async generator that yields a session and ensures
cleanup on exit.
"""

from collections.abc import AsyncGenerator, Generator
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from taskmanager.settings import settings

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

engine = create_engine(
    settings.db_url,
    echo=settings.debug,
    pool_pre_ping=True,
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

# ---------------------------------------------------------------------------
# get_db helpers
# ---------------------------------------------------------------------------


def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy ``Session`` and close it when the caller exits.

    Intended for use as a FastAPI dependency or with a ``with`` block.
    """
    db: Optional[Session] = None
    try:
        db = SessionLocal()
        yield db
    finally:
        if db is not None:
            db.close()


async def get_async_db() -> AsyncGenerator[Session, None]:
    """Async variant of :func:`get_db` for async endpoints."""
    db: Optional[Session] = None
    try:
        db = SessionLocal()
        yield db
    finally:
        if db is not None:
            db.close()
