"""Pytest fixtures for API tests.

This module provides reusable fixtures for testing API endpoints,
including test database setup, FastAPI test client, and sample data.
"""

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from taskmanager.api.app import create_app
from taskmanager.database import Base
from taskmanager.models import Task


@pytest.fixture
def test_db() -> Iterator[Session]:
    """Create an in-memory SQLite database session for testing.

    This fixture creates a fresh database for each test, ensuring isolation.
    The database is automatically cleaned up after the test completes.

    Yields:
        Session: A SQLAlchemy session connected to an in-memory database.
    """
    # Ensure we're in test environment
    os.environ["ENVIRONMENT"] = "test"

    # Create in-memory SQLite database
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    # Create session factory and session
    session_factory = sessionmaker(bind=engine)
    session = session_factory()

    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def test_client() -> TestClient:
    """Create a FastAPI test client.

    Returns:
        TestClient: A test client for making requests to the FastAPI app.
    """
    # Ensure we're in test environment
    os.environ["ENVIRONMENT"] = "test"

    # Use app factory instead of importing app directly
    app = create_app()
    return TestClient(app)


@pytest.fixture
def sample_task(test_db: Session) -> Task:
    """Create a sample task for testing.

    Args:
        test_db: Database session fixture.

    Returns:
        Task: A persisted task instance.
    """
    task = Task(
        name="test-task",
        command="echo 'Hello, World!'",
        description="A test task for unit tests",
        shell="/bin/bash",
    )
    test_db.add(task)
    test_db.commit()
    test_db.refresh(task)
    return task
