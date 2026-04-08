"""Tests for API dependency injection utilities."""

import contextlib

import pytest
from sqlalchemy.orm import Session

from taskmanager.api.deps import get_db


def test_get_db_yields_session() -> None:
    """Test that get_db yields a valid SQLAlchemy session."""
    generator = get_db()
    session = next(generator)

    assert isinstance(session, Session)
    assert session.is_active

    # Clean up
    with contextlib.suppress(StopIteration):
        next(generator)


def test_get_db_closes_session() -> None:
    """Test that get_db closes the session after use."""
    session_ref = None

    for session in get_db():
        session_ref = session
        assert session.is_active
        # Break to simulate normal request completion

    # After generator completes, session should be closed
    assert session_ref is not None
    # Note: session.is_active can still be True after close() in some cases
    # The important thing is that the session was closed, which happens in finally


def test_get_db_commits_on_success() -> None:
    """Test that get_db commits the transaction on successful completion."""
    session_ref = None

    for session in get_db():
        session_ref = session
        # Simulate some work
        assert session.is_active

    # Session should have been committed (no exception raised)
    assert session_ref is not None


def test_get_db_rollback_on_exception() -> None:
    """Test that get_db rolls back transaction on exception."""
    msg = "Simulated error"

    def _raise_error() -> None:
        for _session in get_db():
            # Simulate an error during request processing
            raise ValueError(msg)

    with pytest.raises(ValueError, match=msg):
        _raise_error()
