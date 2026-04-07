"""Tests for database engine, session lifecycle, and Task model."""

import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from taskmanager.database import Base, get_db, get_engine, get_session_factory
from taskmanager.models import Task
from taskmanager.settings import get_settings


IN_MEMORY_DB_URL = "sqlite:///:memory:"


# ---------------------------------------------------------------------------
# Engine creation
# ---------------------------------------------------------------------------


def test_get_engine_returns_engine():
    """get_engine should return a usable SQLAlchemy engine."""
    engine = get_engine(IN_MEMORY_DB_URL)
    assert engine is not None
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        assert result.scalar() == 1
    engine.dispose()


def test_get_engine_uses_settings_default(monkeypatch):
    """When no url is passed, get_engine reads from settings."""
    monkeypatch.setenv("DB_URL", IN_MEMORY_DB_URL)
    get_settings.cache_clear()
    engine = get_engine()
    assert engine is not None
    engine.dispose()


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------


def test_get_session_factory_creates_sessions():
    """get_session_factory should produce working sessions."""
    factory = get_session_factory(IN_MEMORY_DB_URL)
    session = factory()
    assert isinstance(session, Session)
    session.close()


# ---------------------------------------------------------------------------
# Table creation via Base.metadata
# ---------------------------------------------------------------------------


def test_create_all_creates_tasks_table():
    """Base.metadata.create_all should create the 'tasks' table."""
    engine = create_engine(IN_MEMORY_DB_URL)
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    assert "tasks" in inspector.get_table_names()
    engine.dispose()


def test_tasks_table_columns():
    """The tasks table should have the expected columns."""
    engine = create_engine(IN_MEMORY_DB_URL)
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("tasks")}
    expected = {"id", "name", "command", "description", "shell", "created_at", "updated_at"}
    assert expected == columns
    engine.dispose()


# ---------------------------------------------------------------------------
# get_db context manager
# ---------------------------------------------------------------------------


def test_get_db_yields_session():
    """get_db should yield a usable session."""
    engine = create_engine(IN_MEMORY_DB_URL)
    Base.metadata.create_all(engine)

    with get_db(IN_MEMORY_DB_URL) as session:
        assert isinstance(session, Session)
        result = session.execute(text("SELECT 1"))
        assert result.scalar() == 1


def test_get_db_closes_session_on_exit():
    """Session should be closed after exiting the context manager."""
    with get_db(IN_MEMORY_DB_URL) as session:
        pass

    # After the context manager exits, commit was called and session
    # was closed.  No pending state should remain.
    assert len(session.new) == 0
    assert len(session.dirty) == 0
    assert len(session.deleted) == 0


# ---------------------------------------------------------------------------
# Task model CRUD
# ---------------------------------------------------------------------------


def test_task_insert_and_query(db_session):
    """Insert a task and read it back."""
    task = Task(name="echo-test", command="echo hello")
    db_session.add(task)
    db_session.flush()

    loaded = db_session.get(Task, task.id)
    assert loaded is not None
    assert loaded.name == "echo-test"
    assert loaded.command == "echo hello"
    assert loaded.shell == "/bin/sh"
    assert loaded.description is None


def test_task_default_id_is_uuid(db_session):
    """Task id should default to a valid UUID string."""
    task = Task(name="uuid-test", command="true")
    db_session.add(task)
    db_session.flush()

    # Should be parseable as UUID
    uuid.UUID(task.id)


def test_task_timestamps_auto_populate(db_session):
    """created_at and updated_at should auto-populate on insert."""
    task = Task(name="ts-test", command="date")
    db_session.add(task)
    db_session.flush()

    assert task.created_at is not None
    assert task.updated_at is not None


def test_task_name_unique_constraint(db_session):
    """Duplicate task names should violate the unique constraint."""
    task1 = Task(name="dup", command="cmd1")
    task2 = Task(name="dup", command="cmd2")
    db_session.add(task1)
    db_session.flush()

    db_session.add(task2)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_task_repr(db_session):
    """Task.__repr__ should contain id and name."""
    task = Task(name="repr-test", command="ls")
    db_session.add(task)
    db_session.flush()

    r = repr(task)
    assert "repr-test" in r
    assert task.id in r
