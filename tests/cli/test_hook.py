"""Tests for hook CLI commands."""

import pytest
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from taskmanager.cli import app
from taskmanager.database import Base
from taskmanager.models import ActionType
from taskmanager.services.hook_service import create_hook
from taskmanager.services.task_service import create_task


runner = CliRunner()


@pytest.fixture
def setup_db(db_engine):
    """Set up database tables before each test."""
    Base.metadata.create_all(db_engine)
    yield
    Base.metadata.drop_all(db_engine)


@pytest.fixture
def mock_db(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Session:
    """Mock get_db to return the test session."""
    from collections.abc import Iterator
    from contextlib import contextmanager

    @contextmanager
    def _get_test_db() -> Iterator[Session]:
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    monkeypatch.setattr("taskmanager.cli.hook.get_db", _get_test_db)
    return db_session


class TestHookAdd:
    """Tests for the 'hook add' command."""

    def test_add_hook_shell_action_success(self, setup_db, mock_db):
        """Test adding a hook with shell action."""
        result = runner.invoke(
            app,
            [
                "hook",
                "add",
                "--name",
                "notify-fail",
                "--on",
                "task.failed",
                "--action",
                "shell",
                "--command",
                "echo Task failed",
            ],
        )

        assert result.exit_code == 0
        assert "Hook 'notify-fail' created" in result.stdout
        assert "✓" in result.stdout

    def test_add_hook_webhook_action_success(self, setup_db, mock_db):
        """Test adding a hook with webhook action."""
        result = runner.invoke(
            app,
            [
                "hook",
                "add",
                "--name",
                "slack-notify",
                "--on",
                "task.completed",
                "--action",
                "webhook",
                "--url",
                "https://hooks.slack.com/services/XXX",
            ],
        )

        assert result.exit_code == 0
        assert "Hook 'slack-notify' created" in result.stdout

    def test_add_hook_log_action_success(self, setup_db, mock_db):
        """Test adding a hook with log action."""
        result = runner.invoke(
            app,
            [
                "hook",
                "add",
                "--name",
                "log-event",
                "--on",
                "task.started",
                "--action",
                "log",
            ],
        )

        assert result.exit_code == 0
        assert "Hook 'log-event' created" in result.stdout

    def test_add_hook_with_task_filter(self, setup_db, mock_db):
        """Test adding a hook with task filter."""
        # Create a task first
        task = create_task(mock_db, name="backup", command="rsync -av /data /backup")

        result = runner.invoke(
            app,
            [
                "hook",
                "add",
                "--name",
                "backup-notify",
                "--on",
                "task.completed",
                "--action",
                "shell",
                "--command",
                "echo Backup done",
                "--task",
                task.id,
            ],
        )

        assert result.exit_code == 0
        assert "Hook 'backup-notify' created" in result.stdout

    def test_add_hook_duplicate_name(self, setup_db, mock_db):
        """Test that adding a duplicate hook name fails."""
        # Create initial hook
        create_hook(
            mock_db,
            name="notify",
            event_type="task.failed",
            action_type=ActionType.SHELL,
            action_config='{"command": "echo failed"}',
        )

        # Try to create duplicate
        result = runner.invoke(
            app,
            [
                "hook",
                "add",
                "--name",
                "notify",
                "--on",
                "task.completed",
                "--action",
                "shell",
                "--command",
                "echo done",
            ],
        )

        assert result.exit_code == 1
        # Error messages go to stderr
        output = result.stdout + result.stderr
        assert "Error" in output
        assert "notify" in output

    def test_add_hook_shell_without_command(self, setup_db, mock_db):
        """Test that shell action without --command fails."""
        result = runner.invoke(
            app,
            [
                "hook",
                "add",
                "--name",
                "notify",
                "--on",
                "task.failed",
                "--action",
                "shell",
            ],
        )

        assert result.exit_code == 1
        # Error messages go to stderr
        output = result.stdout + result.stderr
        assert "Error" in output
        assert "--command is required" in output

    def test_add_hook_webhook_without_url(self, setup_db, mock_db):
        """Test that webhook action without --url fails."""
        result = runner.invoke(
            app,
            [
                "hook",
                "add",
                "--name",
                "slack",
                "--on",
                "task.failed",
                "--action",
                "webhook",
            ],
        )

        assert result.exit_code == 1
        # Error messages go to stderr
        output = result.stdout + result.stderr
        assert "Error" in output
        assert "--url is required" in output

    def test_add_hook_invalid_action_type(self, setup_db, mock_db):
        """Test that invalid action type fails."""
        result = runner.invoke(
            app,
            [
                "hook",
                "add",
                "--name",
                "notify",
                "--on",
                "task.failed",
                "--action",
                "invalid",
            ],
        )

        assert result.exit_code == 1
        # Error messages go to stderr
        output = result.stdout + result.stderr
        assert "Error" in output
        assert "Invalid action type" in output


class TestHookList:
    """Tests for the 'hook list' command."""

    def test_list_hooks_empty(self, setup_db, mock_db):
        """Test listing hooks when none exist."""
        result = runner.invoke(app, ["hook", "list"])

        assert result.exit_code == 0
        assert "No hooks found" in result.stdout

    def test_list_hooks_all(self, setup_db, mock_db):
        """Test listing all hooks."""
        # Create multiple hooks
        create_hook(
            mock_db,
            name="hook1",
            event_type="task.started",
            action_type=ActionType.SHELL,
            action_config='{"command": "echo started"}',
        )
        create_hook(
            mock_db,
            name="hook2",
            event_type="task.completed",
            action_type=ActionType.WEBHOOK,
            action_config='{"url": "https://example.com"}',
        )
        create_hook(
            mock_db,
            name="hook3",
            event_type="task.failed",
            action_type=ActionType.LOG,
            action_config="{}",
            enabled=False,
        )

        result = runner.invoke(app, ["hook", "list"])

        assert result.exit_code == 0
        assert "hook1" in result.stdout
        assert "hook2" in result.stdout
        assert "hook3" in result.stdout
        assert "task.started" in result.stdout
        assert "task.completed" in result.stdout
        assert "task.failed" in result.stdout

    def test_list_hooks_disabled_only(self, setup_db, mock_db):
        """Test listing only disabled hooks."""
        # Create enabled and disabled hooks
        create_hook(
            mock_db,
            name="enabled-hook",
            event_type="task.started",
            action_type=ActionType.SHELL,
            action_config='{"command": "echo started"}',
            enabled=True,
        )
        create_hook(
            mock_db,
            name="disabled-hook",
            event_type="task.failed",
            action_type=ActionType.LOG,
            action_config="{}",
            enabled=False,
        )

        result = runner.invoke(app, ["hook", "list", "--disabled"])

        assert result.exit_code == 0
        assert "disabled-hook" in result.stdout
        assert "enabled-hook" not in result.stdout


class TestHookShow:
    """Tests for the 'hook show' command."""

    def test_show_hook_exists(self, setup_db, mock_db):
        """Test showing details of an existing hook."""
        create_hook(
            mock_db,
            name="test-hook",
            event_type="task.completed",
            action_type=ActionType.SHELL,
            action_config='{"command": "echo done"}',
        )

        result = runner.invoke(app, ["hook", "show", "test-hook"])

        assert result.exit_code == 0
        assert "test-hook" in result.stdout
        assert "task.completed" in result.stdout
        assert "shell" in result.stdout
        assert "echo done" in result.stdout

    def test_show_hook_not_found(self, setup_db, mock_db):
        """Test showing a non-existent hook."""
        result = runner.invoke(app, ["hook", "show", "nonexistent"])

        assert result.exit_code == 1
        # Error messages go to stderr
        output = result.stdout + result.stderr
        assert "Error" in output
        assert "not found" in output


class TestHookEnable:
    """Tests for the 'hook enable' command."""

    def test_enable_hook_success(self, setup_db, mock_db):
        """Test enabling a disabled hook."""
        create_hook(
            mock_db,
            name="test-hook",
            event_type="task.failed",
            action_type=ActionType.SHELL,
            action_config='{"command": "echo failed"}',
            enabled=False,
        )

        result = runner.invoke(app, ["hook", "enable", "test-hook"])

        assert result.exit_code == 0
        assert "Hook 'test-hook' enabled" in result.stdout
        assert "✓" in result.stdout

    def test_enable_hook_not_found(self, setup_db, mock_db):
        """Test enabling a non-existent hook."""
        result = runner.invoke(app, ["hook", "enable", "nonexistent"])

        assert result.exit_code == 1
        # Error messages go to stderr
        output = result.stdout + result.stderr
        assert "Error" in output
        assert "not found" in output


class TestHookDisable:
    """Tests for the 'hook disable' command."""

    def test_disable_hook_success(self, setup_db, mock_db):
        """Test disabling an enabled hook."""
        create_hook(
            mock_db,
            name="test-hook",
            event_type="task.completed",
            action_type=ActionType.SHELL,
            action_config='{"command": "echo done"}',
            enabled=True,
        )

        result = runner.invoke(app, ["hook", "disable", "test-hook"])

        assert result.exit_code == 0
        assert "Hook 'test-hook' disabled" in result.stdout
        assert "✓" in result.stdout

    def test_disable_hook_not_found(self, setup_db, mock_db):
        """Test disabling a non-existent hook."""
        result = runner.invoke(app, ["hook", "disable", "nonexistent"])

        assert result.exit_code == 1
        # Error messages go to stderr
        output = result.stdout + result.stderr
        assert "Error" in output
        assert "not found" in output


class TestHookRemove:
    """Tests for the 'hook remove' command."""

    def test_remove_hook_with_yes_flag(self, setup_db, mock_db):
        """Test removing a hook with --yes flag."""
        create_hook(
            mock_db,
            name="test-hook",
            event_type="task.failed",
            action_type=ActionType.SHELL,
            action_config='{"command": "echo failed"}',
        )

        result = runner.invoke(app, ["hook", "remove", "test-hook", "--yes"])

        assert result.exit_code == 0
        assert "Hook 'test-hook' removed" in result.stdout
        assert "✓" in result.stdout

    def test_remove_hook_not_found(self, setup_db, mock_db):
        """Test removing a non-existent hook."""
        result = runner.invoke(app, ["hook", "remove", "nonexistent", "--yes"])

        assert result.exit_code == 1
        # Error messages go to stderr
        output = result.stdout + result.stderr
        assert "Error" in output
        assert "not found" in output

    def test_remove_hook_confirmation_cancelled(self, setup_db, mock_db):
        """Test that cancelling confirmation doesn't remove the hook."""
        create_hook(
            mock_db,
            name="test-hook",
            event_type="task.failed",
            action_type=ActionType.SHELL,
            action_config='{"command": "echo failed"}',
        )

        # Simulate user typing 'n' for no
        result = runner.invoke(app, ["hook", "remove", "test-hook"], input="n\n")

        assert result.exit_code == 0
        assert "Cancelled" in result.stdout


class TestHookCLIIntegration:
    """Integration tests for hook CLI commands."""

    def test_add_list_show_remove_workflow(self, setup_db, mock_db):
        """Test complete workflow: add -> list -> show -> remove."""
        # Add a hook
        result = runner.invoke(
            app,
            [
                "hook",
                "add",
                "--name",
                "workflow-test",
                "--on",
                "task.completed",
                "--action",
                "shell",
                "--command",
                "echo workflow test",
            ],
        )
        assert result.exit_code == 0

        # List hooks
        result = runner.invoke(app, ["hook", "list"])
        assert result.exit_code == 0
        assert "workflow-test" in result.stdout

        # Show hook details
        result = runner.invoke(app, ["hook", "show", "workflow-test"])
        assert result.exit_code == 0
        assert "workflow-test" in result.stdout
        assert "echo workflow test" in result.stdout

        # Remove hook
        result = runner.invoke(app, ["hook", "remove", "workflow-test", "--yes"])
        assert result.exit_code == 0

        # Verify removed
        result = runner.invoke(app, ["hook", "list"])
        assert result.exit_code == 0
        assert "No hooks found" in result.stdout

    def test_enable_disable_workflow(self, setup_db, mock_db):
        """Test enable/disable workflow."""
        # Add a hook
        create_hook(
            mock_db,
            name="toggle-test",
            event_type="task.started",
            action_type=ActionType.LOG,
            action_config="{}",
            enabled=True,
        )

        # Disable the hook
        result = runner.invoke(app, ["hook", "disable", "toggle-test"])
        assert result.exit_code == 0
        assert "disabled" in result.stdout

        # Enable the hook
        result = runner.invoke(app, ["hook", "enable", "toggle-test"])
        assert result.exit_code == 0
        assert "enabled" in result.stdout
