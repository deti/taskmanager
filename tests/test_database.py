"""Tests for database engine, session lifecycle, and Task model."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from taskmanager.database import Base, get_db, get_engine, get_session_factory
from taskmanager.models import Run, RunStatus, Task
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


def test_create_all_creates_runs_table():
    """Base.metadata.create_all should create the 'runs' table."""
    engine = create_engine(IN_MEMORY_DB_URL)
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    assert "runs" in inspector.get_table_names()
    engine.dispose()


def test_runs_table_columns():
    """The runs table should have the expected columns."""
    engine = create_engine(IN_MEMORY_DB_URL)
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("runs")}
    expected = {
        "id",
        "task_id",
        "status",
        "command_snapshot",
        "started_at",
        "finished_at",
        "exit_code",
        "stdout",
        "stderr",
        "duration_ms",
        "error_message",
    }
    assert expected == columns
    engine.dispose()


def test_runs_table_has_foreign_key():
    """The runs table should have a foreign key to tasks."""
    engine = create_engine(IN_MEMORY_DB_URL)
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    foreign_keys = inspector.get_foreign_keys("runs")
    assert len(foreign_keys) == 1
    assert foreign_keys[0]["referred_table"] == "tasks"
    assert foreign_keys[0]["constrained_columns"] == ["task_id"]
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


# ---------------------------------------------------------------------------
# Run model CRUD
# ---------------------------------------------------------------------------


def test_run_insert_and_query(db_session):
    """Insert a run and read it back."""
    task = Task(name="run-test-task", command="echo test")
    db_session.add(task)
    db_session.flush()

    run = Run(task_id=task.id, command_snapshot="echo test")
    db_session.add(run)
    db_session.flush()

    loaded = db_session.get(Run, run.id)
    assert loaded is not None
    assert loaded.task_id == task.id
    assert loaded.status == RunStatus.PENDING
    assert loaded.command_snapshot == "echo test"
    assert loaded.stdout == ""
    assert loaded.stderr == ""


def test_run_default_id_is_uuid(db_session):
    """Run id should default to a valid UUID string."""
    task = Task(name="run-uuid-task", command="true")
    db_session.add(task)
    db_session.flush()

    run = Run(task_id=task.id, command_snapshot="true")
    db_session.add(run)
    db_session.flush()

    # Should be parseable as UUID
    uuid.UUID(run.id)


def test_run_status_enum(db_session):
    """Run status should accept all RunStatus enum values."""
    task = Task(name="status-task", command="test")
    db_session.add(task)
    db_session.flush()

    for status in RunStatus:
        run = Run(
            task_id=task.id,
            command_snapshot="test",
            status=status,
        )
        db_session.add(run)
        db_session.flush()

        loaded = db_session.get(Run, run.id)
        assert loaded is not None
        assert loaded.status == status


def test_run_with_full_execution_data(db_session):
    """Insert a run with all execution tracking fields."""
    task = Task(name="full-run-task", command="echo hello")
    db_session.add(task)
    db_session.flush()

    now = datetime.now(UTC)
    run = Run(
        task_id=task.id,
        command_snapshot="echo hello",
        status=RunStatus.SUCCESS,
        started_at=now,
        finished_at=now,
        exit_code=0,
        stdout="hello\n",
        stderr="",
        duration_ms=42,
    )
    db_session.add(run)
    db_session.flush()

    loaded = db_session.get(Run, run.id)
    assert loaded is not None
    assert loaded.status == RunStatus.SUCCESS
    assert loaded.exit_code == 0
    assert loaded.stdout == "hello\n"
    assert loaded.stderr == ""
    assert loaded.duration_ms == 42


def test_run_with_error(db_session):
    """Insert a run with error tracking."""
    task = Task(name="error-task", command="false")
    db_session.add(task)
    db_session.flush()

    run = Run(
        task_id=task.id,
        command_snapshot="false",
        status=RunStatus.FAILED,
        exit_code=1,
        error_message="Command failed with exit code 1",
    )
    db_session.add(run)
    db_session.flush()

    loaded = db_session.get(Run, run.id)
    assert loaded is not None
    assert loaded.status == RunStatus.FAILED
    assert loaded.exit_code == 1
    assert loaded.error_message == "Command failed with exit code 1"


def test_run_foreign_key_constraint(db_session):
    """Run with invalid task_id should violate foreign key constraint."""
    fake_task_id = str(uuid.uuid4())
    run = Run(task_id=fake_task_id, command_snapshot="test")
    db_session.add(run)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_run_repr(db_session):
    """Run.__repr__ should contain id, task_id, and status."""
    task = Task(name="repr-task", command="ls")
    db_session.add(task)
    db_session.flush()

    run = Run(task_id=task.id, command_snapshot="ls")
    db_session.add(run)
    db_session.flush()

    r = repr(run)
    assert run.id in r
    assert task.id in r
    assert "pending" in r
