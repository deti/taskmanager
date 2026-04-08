"""Unit tests for Hook ORM model."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from taskmanager.database import Base
from taskmanager.models import ActionType, Hook, Task


@pytest.fixture
def engine():
    """Create an in-memory SQLite engine for testing."""
    from sqlalchemy import event

    engine = create_engine("sqlite:///:memory:")

    # Enable foreign key constraints in SQLite
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    """Create a database session for testing."""
    with Session(engine) as session:
        yield session


@pytest.fixture
def sample_task(session):
    """Create a sample task for hook testing."""
    task = Task(
        name="sample-task",
        command="echo 'test'",
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def test_hook_creation_with_all_fields(session, sample_task):
    """Test Hook creation with all fields populated."""
    hook = Hook(
        name="task-completion-hook",
        event_type="task.completed",
        task_filter=sample_task.id,
        action_type=ActionType.SHELL,
        action_config='{"command": "echo done"}',
        enabled=True,
    )
    session.add(hook)
    session.commit()
    session.refresh(hook)

    assert hook.id is not None
    assert len(hook.id) == 36  # UUID string length
    assert hook.name == "task-completion-hook"
    assert hook.event_type == "task.completed"
    assert hook.task_filter == sample_task.id
    assert hook.action_type == ActionType.SHELL
    assert hook.action_config == '{"command": "echo done"}'
    assert hook.enabled is True
    assert isinstance(hook.created_at, datetime)
    assert isinstance(hook.updated_at, datetime)


def test_hook_creation_with_nullable_task_filter(session):
    """Test Hook creation with task_filter=None (global hook)."""
    hook = Hook(
        name="global-hook",
        event_type="task.completed",
        task_filter=None,
        action_type=ActionType.LOG,
        action_config='{"level": "info"}',
    )
    session.add(hook)
    session.commit()
    session.refresh(hook)

    assert hook.task_filter is None
    assert hook.event_type == "task.completed"
    assert hook.action_type == ActionType.LOG


def test_hook_unique_constraint_violation(session):
    """Test unique constraint violation on duplicate name."""
    hook1 = Hook(
        name="duplicate-name",
        event_type="task.started",
        action_type=ActionType.WEBHOOK,
        action_config='{"url": "http://example.com"}',
    )
    session.add(hook1)
    session.commit()

    hook2 = Hook(
        name="duplicate-name",
        event_type="task.completed",
        action_type=ActionType.LOG,
        action_config='{"level": "debug"}',
    )
    session.add(hook2)

    with pytest.raises(IntegrityError):
        session.commit()


def test_hook_default_values(session):
    """Test default values (enabled=True, timestamps auto-set)."""
    hook = Hook(
        name="default-values-hook",
        event_type="schedule.fired",
        action_type=ActionType.SHELL,
        action_config='{"command": "ls"}',
    )
    session.add(hook)
    session.commit()
    session.refresh(hook)

    # Check defaults
    assert hook.enabled is True
    assert hook.task_filter is None
    assert hook.created_at is not None
    assert hook.updated_at is not None
    assert isinstance(hook.created_at, datetime)
    assert isinstance(hook.updated_at, datetime)


def test_hook_action_type_enum_values(session):
    """Test ActionType enum values and serialization."""
    # Test SHELL
    hook_shell = Hook(
        name="shell-hook",
        event_type="test.event",
        action_type=ActionType.SHELL,
        action_config='{"command": "echo test"}',
    )
    session.add(hook_shell)
    session.commit()
    session.refresh(hook_shell)
    assert hook_shell.action_type == ActionType.SHELL
    assert hook_shell.action_type.value == "shell"

    # Test WEBHOOK
    hook_webhook = Hook(
        name="webhook-hook",
        event_type="test.event",
        action_type=ActionType.WEBHOOK,
        action_config='{"url": "http://example.com"}',
    )
    session.add(hook_webhook)
    session.commit()
    session.refresh(hook_webhook)
    assert hook_webhook.action_type == ActionType.WEBHOOK
    assert hook_webhook.action_type.value == "webhook"

    # Test LOG
    hook_log = Hook(
        name="log-hook",
        event_type="test.event",
        action_type=ActionType.LOG,
        action_config='{"level": "info"}',
    )
    session.add(hook_log)
    session.commit()
    session.refresh(hook_log)
    assert hook_log.action_type == ActionType.LOG
    assert hook_log.action_type.value == "log"


def test_hook_repr_output_format(session):
    """Verify __repr__ output format."""
    hook = Hook(
        name="repr-test-hook",
        event_type="task.completed",
        action_type=ActionType.SHELL,
        action_config='{"command": "echo done"}',
    )
    session.add(hook)
    session.commit()
    session.refresh(hook)

    repr_str = repr(hook)
    assert repr_str.startswith("<Hook(")
    assert f"id={hook.id!r}" in repr_str
    assert "name='repr-test-hook'" in repr_str
    assert "event_type='task.completed'" in repr_str
    assert "action_type='shell'" in repr_str
    assert repr_str.endswith(")>")


def test_hook_foreign_key_to_task(session, sample_task):
    """Test that task_filter correctly references a Task."""
    hook = Hook(
        name="task-scoped-hook",
        event_type="task.completed",
        task_filter=sample_task.id,
        action_type=ActionType.LOG,
        action_config='{"level": "info"}',
    )
    session.add(hook)
    session.commit()

    # Query back and verify foreign key
    queried_hook = session.query(Hook).filter_by(name="task-scoped-hook").first()
    assert queried_hook is not None
    assert queried_hook.task_filter == sample_task.id


def test_hook_invalid_task_filter_foreign_key(session):
    """Test that invalid task_filter (non-existent task ID) fails."""
    fake_task_id = str(uuid.uuid4())
    hook = Hook(
        name="invalid-fk-hook",
        event_type="task.completed",
        task_filter=fake_task_id,
        action_type=ActionType.LOG,
        action_config='{"level": "info"}',
    )
    session.add(hook)

    with pytest.raises(IntegrityError):
        session.flush()
