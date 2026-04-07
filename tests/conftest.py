"""Shared test fixtures."""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from taskmanager.database import Base
from taskmanager.settings import get_settings


IN_MEMORY_DB_URL = "sqlite:///:memory:"


@pytest.fixture(autouse=True)
def _test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set ENVIRONMENT=test and clear the settings cache for every test."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()
    yield  # type: ignore[misc]
    get_settings.cache_clear()


@pytest.fixture
def db_engine():
    """Create an in-memory SQLite engine with all tables."""
    engine = create_engine(IN_MEMORY_DB_URL)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db_session(db_engine) -> Iterator[Session]:
    """Yield a SQLAlchemy session bound to the in-memory database."""
    factory = sessionmaker(bind=db_engine)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
