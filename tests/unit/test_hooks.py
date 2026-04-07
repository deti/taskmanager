"""Unit tests for HookService and HookProcessor."""

import json
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from taskmanager.database import Base
from taskmanager.exceptions import (
    DuplicateHookError,
    HookNotFoundError,
    HookValidationError,
    TaskNotFoundError,
)
from taskmanager.hooks import HookProcessor
from taskmanager.models import ActionType, Hook, Task
from taskmanager.services import hook_service


@pytest.fixture
def engine():
    """Create an in-memory SQLite engine for testing."""
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


# --- HookService Tests ---


def test_create_hook_with_valid_shell_config(session, sample_task):
    """Test HookService.create_hook with valid SHELL action."""
    hook = hook_service.create_hook(
        session=session,
        name="test-shell-hook",
        event_type="task.completed",
        action_type=ActionType.SHELL,
        action_config='{"command": "echo done"}',
        task_filter=sample_task.id,
    )
    session.commit()
    session.refresh(hook)

    assert hook.id is not None
    assert hook.name == "test-shell-hook"
    assert hook.event_type == "task.completed"
    assert hook.action_type == ActionType.SHELL
    assert hook.task_filter == sample_task.id
    assert hook.enabled is True


def test_create_hook_with_valid_webhook_config(session):
    """Test HookService.create_hook with valid WEBHOOK action."""
    hook = hook_service.create_hook(
        session=session,
        name="test-webhook-hook",
        event_type="task.failed",
        action_type=ActionType.WEBHOOK,
        action_config='{"url": "http://example.com/webhook"}',
    )
    session.commit()
    session.refresh(hook)

    assert hook.name == "test-webhook-hook"
    assert hook.action_type == ActionType.WEBHOOK
    assert hook.task_filter is None  # Global hook


def test_create_hook_with_valid_log_config(session):
    """Test HookService.create_hook with valid LOG action."""
    hook = hook_service.create_hook(
        session=session,
        name="test-log-hook",
        event_type="task.started",
        action_type=ActionType.LOG,
        action_config='{"level": "info", "message": "Task started"}',
    )
    session.commit()

    assert hook.name == "test-log-hook"
    assert hook.action_type == ActionType.LOG


def test_create_hook_with_duplicate_name_raises_error(session):
    """Test HookService.create_hook with duplicate name raises DuplicateHookError."""
    hook_service.create_hook(
        session=session,
        name="duplicate-hook",
        event_type="task.completed",
        action_type=ActionType.LOG,
        action_config='{"level": "info"}',
    )
    session.commit()

    with pytest.raises(DuplicateHookError) as exc_info:
        hook_service.create_hook(
            session=session,
            name="duplicate-hook",
            event_type="task.failed",
            action_type=ActionType.LOG,
            action_config='{"level": "error"}',
        )

    assert exc_info.value.name == "duplicate-hook"


def test_create_hook_with_invalid_task_filter_raises_error(session):
    """Test HookService.create_hook with invalid task_filter FK raises TaskNotFoundError."""
    fake_task_id = str(uuid.uuid4())

    with pytest.raises(TaskNotFoundError) as exc_info:
        hook_service.create_hook(
            session=session,
            name="invalid-fk-hook",
            event_type="task.completed",
            action_type=ActionType.LOG,
            action_config='{"level": "info"}',
            task_filter=fake_task_id,
        )

    assert exc_info.value.task_id == fake_task_id


def test_create_hook_with_invalid_json_raises_error(session):
    """Test HookService.create_hook with invalid JSON raises HookValidationError."""
    with pytest.raises(HookValidationError) as exc_info:
        hook_service.create_hook(
            session=session,
            name="invalid-json-hook",
            event_type="task.completed",
            action_type=ActionType.SHELL,
            action_config="not valid json",
        )

    assert "Invalid JSON" in exc_info.value.message


def test_create_hook_shell_missing_command_raises_error(session):
    """Test HookService.create_hook SHELL without 'command' raises HookValidationError."""
    with pytest.raises(HookValidationError) as exc_info:
        hook_service.create_hook(
            session=session,
            name="missing-command-hook",
            event_type="task.completed",
            action_type=ActionType.SHELL,
            action_config='{"foo": "bar"}',
        )

    assert "requires 'command'" in exc_info.value.message


def test_create_hook_shell_empty_command_raises_error(session):
    """Test HookService.create_hook SHELL with empty command raises HookValidationError."""
    with pytest.raises(HookValidationError) as exc_info:
        hook_service.create_hook(
            session=session,
            name="empty-command-hook",
            event_type="task.completed",
            action_type=ActionType.SHELL,
            action_config='{"command": "   "}',
        )

    assert "cannot be empty" in exc_info.value.message


def test_create_hook_webhook_missing_url_raises_error(session):
    """Test HookService.create_hook WEBHOOK without 'url' raises HookValidationError."""
    with pytest.raises(HookValidationError) as exc_info:
        hook_service.create_hook(
            session=session,
            name="missing-url-hook",
            event_type="task.completed",
            action_type=ActionType.WEBHOOK,
            action_config='{"foo": "bar"}',
        )

    assert "requires 'url'" in exc_info.value.message


def test_create_hook_empty_name_raises_error(session):
    """Test HookService.create_hook with empty name raises HookValidationError."""
    with pytest.raises(HookValidationError) as exc_info:
        hook_service.create_hook(
            session=session,
            name="   ",
            event_type="task.completed",
            action_type=ActionType.LOG,
            action_config='{"level": "info"}',
        )

    assert "name cannot be empty" in exc_info.value.message


def test_create_hook_empty_event_type_raises_error(session):
    """Test HookService.create_hook with empty event_type raises HookValidationError."""
    with pytest.raises(HookValidationError) as exc_info:
        hook_service.create_hook(
            session=session,
            name="test-hook",
            event_type="",
            action_type=ActionType.LOG,
            action_config='{"level": "info"}',
        )

    assert "event_type cannot be empty" in exc_info.value.message


def test_list_hooks_returns_all_hooks(session):
    """Test HookService.list_hooks returns all hooks."""
    hook_service.create_hook(
        session=session,
        name="hook-1",
        event_type="task.completed",
        action_type=ActionType.LOG,
        action_config='{"level": "info"}',
    )
    hook_service.create_hook(
        session=session,
        name="hook-2",
        event_type="task.failed",
        action_type=ActionType.LOG,
        action_config='{"level": "error"}',
    )
    session.commit()

    hooks = hook_service.list_hooks(session)
    assert len(hooks) == 2
    assert {h.name for h in hooks} == {"hook-1", "hook-2"}


def test_list_hooks_filters_by_enabled_status(session):
    """Test HookService.list_hooks filters by enabled status."""
    hook_service.create_hook(
        session=session,
        name="enabled-hook",
        event_type="task.completed",
        action_type=ActionType.LOG,
        action_config='{"level": "info"}',
        enabled=True,
    )
    hook_service.create_hook(
        session=session,
        name="disabled-hook",
        event_type="task.failed",
        action_type=ActionType.LOG,
        action_config='{"level": "error"}',
        enabled=False,
    )
    session.commit()

    enabled_hooks = hook_service.list_hooks(session, enabled=True)
    assert len(enabled_hooks) == 1
    assert enabled_hooks[0].name == "enabled-hook"

    disabled_hooks = hook_service.list_hooks(session, enabled=False)
    assert len(disabled_hooks) == 1
    assert disabled_hooks[0].name == "disabled-hook"


def test_get_hook_by_name_returns_hook(session):
    """Test HookService.get_hook_by_name returns correct hook."""
    hook_service.create_hook(
        session=session,
        name="findme-hook",
        event_type="task.completed",
        action_type=ActionType.LOG,
        action_config='{"level": "info"}',
    )
    session.commit()

    hook = hook_service.get_hook_by_name(session, "findme-hook")
    assert hook is not None
    assert hook.name == "findme-hook"


def test_get_hook_by_name_returns_none_if_not_found(session):
    """Test HookService.get_hook_by_name returns None if not found."""
    hook = hook_service.get_hook_by_name(session, "nonexistent")
    assert hook is None


def test_get_hook_raises_not_found_error(session):
    """Test HookService.get_hook raises HookNotFoundError for missing hook."""
    with pytest.raises(HookNotFoundError) as exc_info:
        hook_service.get_hook(session, "nonexistent")

    assert exc_info.value.name == "nonexistent"


def test_update_hook_partial_updates(session):
    """Test HookService.update_hook supports partial updates."""
    hook = hook_service.create_hook(
        session=session,
        name="update-me",
        event_type="task.started",
        action_type=ActionType.LOG,
        action_config='{"level": "debug"}',
    )
    session.commit()

    updated = hook_service.update_hook(
        session=session,
        name="update-me",
        event_type="task.completed",
    )
    session.commit()

    assert updated.event_type == "task.completed"
    assert updated.action_type == ActionType.LOG  # Unchanged
    assert updated.action_config == '{"level": "debug"}'  # Unchanged


def test_update_hook_validates_new_name_uniqueness(session):
    """Test HookService.update_hook raises DuplicateHookError for duplicate new_name."""
    hook_service.create_hook(
        session=session,
        name="hook-1",
        event_type="task.completed",
        action_type=ActionType.LOG,
        action_config='{"level": "info"}',
    )
    hook_service.create_hook(
        session=session,
        name="hook-2",
        event_type="task.failed",
        action_type=ActionType.LOG,
        action_config='{"level": "error"}',
    )
    session.commit()

    with pytest.raises(DuplicateHookError):
        hook_service.update_hook(
            session=session,
            name="hook-1",
            new_name="hook-2",
        )


def test_update_hook_validates_action_config_when_action_type_changes(session):
    """Test HookService.update_hook validates action_config when action_type changes."""
    hook = hook_service.create_hook(
        session=session,
        name="change-action",
        event_type="task.completed",
        action_type=ActionType.LOG,
        action_config='{"level": "info"}',
    )
    session.commit()

    # Change action_type to SHELL, but keep invalid config (missing "command")
    with pytest.raises(HookValidationError) as exc_info:
        hook_service.update_hook(
            session=session,
            name="change-action",
            action_type=ActionType.SHELL,
            # action_config still has {"level": "info"}, no "command"
        )

    assert "requires 'command'" in exc_info.value.message


def test_delete_hook_removes_hook(session):
    """Test HookService.delete_hook removes the hook."""
    hook_service.create_hook(
        session=session,
        name="delete-me",
        event_type="task.completed",
        action_type=ActionType.LOG,
        action_config='{"level": "info"}',
    )
    session.commit()

    deleted = hook_service.delete_hook(session, "delete-me")
    session.commit()

    assert deleted.name == "delete-me"

    # Verify it's gone
    with pytest.raises(HookNotFoundError):
        hook_service.get_hook(session, "delete-me")


def test_enable_hook_toggles_enabled_to_true(session):
    """Test HookService.enable_hook sets enabled=True."""
    hook = hook_service.create_hook(
        session=session,
        name="enable-me",
        event_type="task.completed",
        action_type=ActionType.LOG,
        action_config='{"level": "info"}',
        enabled=False,
    )
    session.commit()

    enabled = hook_service.enable_hook(session, "enable-me")
    session.commit()

    assert enabled.enabled is True


def test_disable_hook_toggles_enabled_to_false(session):
    """Test HookService.disable_hook sets enabled=False."""
    hook = hook_service.create_hook(
        session=session,
        name="disable-me",
        event_type="task.completed",
        action_type=ActionType.LOG,
        action_config='{"level": "info"}',
        enabled=True,
    )
    session.commit()

    disabled = hook_service.disable_hook(session, "disable-me")
    session.commit()

    assert disabled.enabled is False


# --- HookProcessor Tests ---


def test_hook_processor_matches_filter_with_null_task_filter():
    """Test HookProcessor._matches_filter with null task_filter (matches all)."""
    processor = HookProcessor()

    # Mock hook with task_filter=None (global)
    hook = MagicMock()
    hook.task_filter = None

    payload = {"task_id": "some-task-id"}

    assert processor._matches_filter(hook, payload) is True


def test_hook_processor_matches_filter_with_specific_task_filter():
    """Test HookProcessor._matches_filter with specific task_filter (matches only that task)."""
    processor = HookProcessor()

    hook = MagicMock()
    hook.task_filter = "task-123"

    # Matching task_id
    payload_match = {"task_id": "task-123"}
    assert processor._matches_filter(hook, payload_match) is True

    # Non-matching task_id
    payload_no_match = {"task_id": "task-456"}
    assert processor._matches_filter(hook, payload_no_match) is False


def test_hook_processor_substitute_template_variables():
    """Test HookProcessor._substitute_template_vars substitutes correctly."""
    processor = HookProcessor()

    template = "Task {task_name} (ID: {task_id}) finished with exit code {exit_code}"
    payload = {
        "task_name": "backup",
        "task_id": "task-123",
        "exit_code": 0,
    }

    result = processor._substitute_template_vars(template, payload)
    assert result == "Task backup (ID: task-123) finished with exit code 0"


@patch("taskmanager.hooks.subprocess.run")
def test_hook_processor_execute_shell_action_substitutes_template_variables(mock_run):
    """Test HookProcessor._execute_shell_action substitutes template variables correctly."""
    processor = HookProcessor()

    hook = MagicMock()
    hook.name = "shell-hook"
    hook.action_type = ActionType.SHELL
    hook.action_config = '{"command": "echo Task {task_name} completed"}'

    payload = {"task_name": "backup"}

    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    processor._execute_shell_action(hook, payload)

    # Verify subprocess.run was called with substituted command
    mock_run.assert_called_once()
    call_kwargs = mock_run.call_args[1]
    assert "echo Task backup completed" in str(call_kwargs) or mock_run.call_args[0][
        0
    ] == "echo Task backup completed"


@patch("taskmanager.hooks.httpx.post")
def test_hook_processor_execute_webhook_action_posts_json_payload(mock_post):
    """Test HookProcessor._execute_webhook_action POSTs JSON payload."""
    processor = HookProcessor()

    hook = MagicMock()
    hook.name = "webhook-hook"
    hook.action_type = ActionType.WEBHOOK
    hook.action_config = '{"url": "http://example.com/webhook"}'

    payload = {"task_name": "backup", "status": "success"}

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "OK"
    mock_post.return_value = mock_response

    processor._execute_webhook_action(hook, payload)

    # Verify httpx.post was called with correct URL and payload
    mock_post.assert_called_once_with(
        "http://example.com/webhook",
        json=payload,
        timeout=10.0,
    )


@patch("taskmanager.hooks.httpx.post")
def test_hook_processor_execute_webhook_action_logs_network_errors_but_doesnt_crash(
    mock_post,
):
    """Test HookProcessor._execute_webhook_action logs network errors but doesn't crash."""
    processor = HookProcessor()

    hook = MagicMock()
    hook.name = "webhook-hook"
    hook.action_config = '{"url": "http://example.com/webhook"}'

    payload = {"task_name": "backup"}

    # Simulate network error
    mock_post.side_effect = httpx.TimeoutException("Connection timeout")

    # Should not raise exception
    processor._execute_webhook_action(hook, payload)

    # Verify the exception was caught (no crash)
    mock_post.assert_called_once()


@patch("taskmanager.hooks.logger")
def test_hook_processor_execute_log_action_emits_structured_log_entry(mock_logger):
    """Test HookProcessor._execute_log_action emits structured log entry."""
    processor = HookProcessor()

    hook = MagicMock()
    hook.name = "log-hook"
    hook.action_config = '{"level": "info"}'

    payload = {"task_name": "backup", "status": "success", "exit_code": 0}

    processor._execute_log_action(hook, payload)

    # Verify logger.info was called with payload
    mock_logger.info.assert_called_once()
    call_args = mock_logger.info.call_args

    # Check that payload fields are included
    assert "hook_log_action" in call_args[0]
    assert call_args[1]["task_name"] == "backup"
    assert call_args[1]["status"] == "success"


@patch("taskmanager.hooks.get_db")
def test_hook_processor_integration_event_triggers_hook_action(
    mock_get_db, session, sample_task, tmp_path
):
    """Integration test: emit event → hook fires → action executes (use temp file for verification)."""
    # Create a hook that writes to a temp file
    output_file = tmp_path / "hook_output.txt"

    hook = hook_service.create_hook(
        session=session,
        name="integration-hook",
        event_type="task.completed",
        action_type=ActionType.SHELL,
        action_config=json.dumps(
            {"command": f"echo 'Task {{task_name}} completed' > {output_file}"}
        ),
        task_filter=sample_task.id,
    )
    session.commit()

    # Mock get_db to return our test session
    mock_get_db.return_value.__enter__.return_value = session
    mock_get_db.return_value.__exit__.return_value = None

    # Create processor and register event type
    processor = HookProcessor()
    processor.register_event_type("task.completed")

    # Emit event
    payload = {
        "event_type": "task.completed",
        "task_id": sample_task.id,
        "task_name": "backup",
    }

    processor._on_event(payload)

    # Verify file was created
    assert output_file.exists()
    content = output_file.read_text().strip()
    assert "Task backup completed" in content
