"""Unit tests for task executor."""

import subprocess
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from taskmanager.database import Base
from taskmanager.events import (
    TASK_COMPLETED,
    TASK_FAILED,
    TASK_STARTED,
    TASK_TIMEOUT,
)
from taskmanager.executor import execute_inline, execute_task
from taskmanager.models import Run, RunStatus, Task


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Create an in-memory SQLite session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)
    session = session_local()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_task(db_session: Session) -> Task:
    """Create a sample task for testing."""
    task = Task(
        name="test-task",
        command="echo hello",
        description="A test task",
        shell="/bin/sh",
    )
    db_session.add(task)
    db_session.commit()
    return task


class TestExecuteTaskSuccess:
    """Tests for successful task execution."""

    def test_success_case_with_stdout(self, db_session: Session, sample_task: Task) -> None:
        """Test successful execution captures stdout correctly."""
        # Arrange
        sample_task.command = "echo hello"

        # Act
        run = execute_task(sample_task, db_session)

        # Assert
        assert run.status == RunStatus.SUCCESS
        assert run.exit_code == 0
        assert "hello" in run.stdout
        assert run.stderr == ""
        assert run.duration_ms is not None
        assert run.duration_ms > 0
        assert run.started_at is not None
        assert run.finished_at is not None
        assert run.error_message is None

    def test_command_snapshot_freezes_command(self, db_session: Session, sample_task: Task) -> None:
        """Test that command_snapshot captures command at execution time."""
        # Arrange
        original_command = "echo original"
        sample_task.command = original_command

        # Act
        run = execute_task(sample_task, db_session)

        # Now modify the task
        sample_task.command = "echo modified"
        db_session.commit()

        # Assert - snapshot should still have the original command
        assert run.command_snapshot == original_command
        assert run.command_snapshot != sample_task.command
        assert "original" in run.stdout


class TestExecuteTaskFailure:
    """Tests for failed task execution."""

    def test_failure_case_with_exit_code(self, db_session: Session, sample_task: Task) -> None:
        """Test failed execution sets status to FAILED with exit code."""
        # Arrange
        sample_task.command = "exit 1"

        # Act
        run = execute_task(sample_task, db_session)

        # Assert
        assert run.status == RunStatus.FAILED
        assert run.exit_code == 1
        assert run.duration_ms is not None
        assert run.duration_ms > 0
        assert run.started_at is not None
        assert run.finished_at is not None

    def test_failure_captures_stderr(self, db_session: Session, sample_task: Task) -> None:
        """Test that stderr is captured on failure."""
        # Arrange
        sample_task.command = "echo error message >&2 && exit 1"

        # Act
        run = execute_task(sample_task, db_session)

        # Assert
        assert run.status == RunStatus.FAILED
        assert run.exit_code == 1
        assert "error message" in run.stderr


class TestExecuteTaskTimeout:
    """Tests for task execution timeout."""

    def test_timeout_sets_failed_status(
        self, db_session: Session, sample_task: Task
    ) -> None:
        """Test that timeout results in FAILED status with error message."""
        # Arrange - mock subprocess.run to raise TimeoutExpired
        sample_task.command = "sleep 10"

        def mock_subprocess_run(*args, **_kwargs):
            # Simulate a timeout by raising TimeoutExpired
            raise subprocess.TimeoutExpired(cmd=args[0] if args else "", timeout=1)

        # Act
        with patch("taskmanager.executor.subprocess.run", side_effect=mock_subprocess_run):
            run = execute_task(sample_task, db_session)

        # Assert
        assert run.status == RunStatus.FAILED
        assert run.error_message is not None
        assert "timed out" in run.error_message.lower()
        assert run.exit_code is None  # No exit code on timeout
        assert run.duration_ms is not None
        assert run.duration_ms >= 0


class TestExecuteTaskDuration:
    """Tests for duration measurement accuracy."""

    def test_duration_within_tolerance(self, db_session: Session, sample_task: Task) -> None:
        """Test that duration_ms is measured accurately."""
        # Arrange - use a command that takes a predictable time
        sample_task.command = "sleep 0.1"

        # Act
        run = execute_task(sample_task, db_session)

        # Assert
        # Sleep 0.1s = 100ms, allow ±50ms tolerance
        assert run.duration_ms is not None
        assert 50 <= run.duration_ms <= 150

    def test_duration_for_instant_command(self, db_session: Session, sample_task: Task) -> None:
        """Test duration for a near-instantaneous command."""
        # Arrange
        sample_task.command = "true"

        # Act
        run = execute_task(sample_task, db_session)

        # Assert
        assert run.duration_ms is not None
        assert run.duration_ms >= 0
        assert run.duration_ms < 100  # Should be very fast


class TestExecuteTaskEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_output(self, db_session: Session, sample_task: Task) -> None:
        """Test execution with no stdout or stderr."""
        # Arrange
        sample_task.command = "true"

        # Act
        run = execute_task(sample_task, db_session)

        # Assert
        assert run.status == RunStatus.SUCCESS
        assert run.stdout == ""
        assert run.stderr == ""

    def test_task_id_is_recorded(self, db_session: Session, sample_task: Task) -> None:
        """Test that Run is correctly linked to Task."""
        # Act
        run = execute_task(sample_task, db_session)

        # Assert
        assert run.task_id == sample_task.id

    def test_run_persisted_to_database(self, db_session: Session, sample_task: Task) -> None:
        """Test that Run is committed and retrievable from database."""
        # Act
        run = execute_task(sample_task, db_session)

        # Assert - query from a fresh session context to verify persistence
        db_session.expire_all()
        retrieved_run = db_session.query(Run).filter_by(id=run.id).first()
        assert retrieved_run is not None
        assert retrieved_run.id == run.id
        assert retrieved_run.task_id == sample_task.id
        assert retrieved_run.status == RunStatus.SUCCESS


class TestExecuteInline:
    """Tests for inline command execution (no task association)."""

    def test_successful_inline_execution(self, db_session: Session) -> None:
        """Test successful inline execution captures output and sets task_id to None."""
        # Act
        run = execute_inline("echo hello", db_session)

        # Assert
        assert run.task_id is None  # Key difference from execute_task
        assert run.status == RunStatus.SUCCESS
        assert run.exit_code == 0
        assert "hello" in run.stdout
        assert run.stderr == ""
        assert run.command_snapshot == "echo hello"
        assert run.duration_ms is not None
        assert run.duration_ms > 0
        assert run.started_at is not None
        assert run.finished_at is not None
        assert run.error_message is None

    def test_failed_inline_execution(self, db_session: Session) -> None:
        """Test failed inline execution sets status to FAILED with exit code."""
        # Act
        run = execute_inline("exit 1", db_session)

        # Assert
        assert run.task_id is None
        assert run.status == RunStatus.FAILED
        assert run.exit_code == 1
        assert run.command_snapshot == "exit 1"
        assert run.duration_ms is not None
        assert run.started_at is not None
        assert run.finished_at is not None

    def test_inline_execution_with_custom_shell(self, db_session: Session) -> None:
        """Test inline execution uses specified shell."""
        # Act - use bash-specific syntax
        run = execute_inline("echo $SHELL", db_session, shell="/bin/bash")

        # Assert
        assert run.task_id is None
        assert run.status == RunStatus.SUCCESS
        assert run.exit_code == 0
        # The command will output the shell path or empty string
        # depending on environment, but should execute without error
        assert run.command_snapshot == "echo $SHELL"

    def test_inline_execution_timeout(self, db_session: Session) -> None:
        """Test inline execution timeout handling."""
        # Arrange - mock subprocess.run to raise TimeoutExpired
        def mock_subprocess_run(*args, **_kwargs):
            # Simulate a timeout by raising TimeoutExpired
            raise subprocess.TimeoutExpired(cmd=args[0] if args else "", timeout=1)

        # Act
        with patch("taskmanager.executor.subprocess.run", side_effect=mock_subprocess_run):
            run = execute_inline("sleep 10", db_session)

        # Assert
        assert run.task_id is None
        assert run.status == RunStatus.FAILED
        assert run.error_message is not None
        assert "timed out" in run.error_message.lower()
        assert run.exit_code is None  # No exit code on timeout
        assert run.duration_ms is not None
        assert run.duration_ms >= 0
        assert run.command_snapshot == "sleep 10"

    def test_inline_run_persisted_to_database(self, db_session: Session) -> None:
        """Test that inline run is persisted with task_id=None in database."""
        # Act
        run = execute_inline("echo test", db_session)

        # Assert - query from a fresh session context to verify persistence
        db_session.expire_all()
        retrieved_run = db_session.query(Run).filter_by(id=run.id).first()
        assert retrieved_run is not None
        assert retrieved_run.id == run.id
        assert retrieved_run.task_id is None  # Verify NULL in database
        assert retrieved_run.status == RunStatus.SUCCESS
        assert retrieved_run.command_snapshot == "echo test"

    def test_inline_execution_with_stderr(self, db_session: Session) -> None:
        """Test that inline execution captures stderr correctly."""
        # Act
        run = execute_inline("echo error >&2 && exit 1", db_session)

        # Assert
        assert run.task_id is None
        assert run.status == RunStatus.FAILED
        assert run.exit_code == 1
        assert "error" in run.stderr
        assert run.command_snapshot == "echo error >&2 && exit 1"

    def test_inline_command_snapshot_immutable(self, db_session: Session) -> None:
        """Test that command_snapshot captures the exact command string."""
        # Act
        original_command = "echo snapshot test"
        run = execute_inline(original_command, db_session)

        # Assert - command_snapshot should match input exactly
        assert run.command_snapshot == original_command
        assert "snapshot test" in run.stdout

    def test_inline_execution_with_empty_output(self, db_session: Session) -> None:
        """Test inline execution with no stdout or stderr."""
        # Act
        run = execute_inline("true", db_session)

        # Assert
        assert run.task_id is None
        assert run.status == RunStatus.SUCCESS
        assert run.exit_code == 0
        assert run.stdout == ""
        assert run.stderr == ""
        assert run.command_snapshot == "true"


class TestEventEmissions:
    """Tests for event bus emissions during task execution."""

    def test_execute_task_emits_started_and_completed_events(
        self, db_session: Session, sample_task: Task
    ) -> None:
        """Test that successful task execution emits TASK_STARTED and TASK_COMPLETED events."""
        # Arrange
        sample_task.command = "echo test"
        mock_event_bus = MagicMock()

        # Act
        with patch("taskmanager.executor.get_event_bus", return_value=mock_event_bus):
            run = execute_task(sample_task, db_session)

        # Assert
        assert run.status == RunStatus.SUCCESS
        assert mock_event_bus.emit.call_count == 2

        # Verify TASK_STARTED event
        started_call = mock_event_bus.emit.call_args_list[0]
        assert started_call[0][0] == TASK_STARTED
        started_payload = started_call[0][1]
        assert started_payload["task_id"] == sample_task.id
        assert started_payload["run_id"] == run.id
        assert started_payload["task_name"] == sample_task.name
        assert "timestamp" in started_payload

        # Verify TASK_COMPLETED event
        completed_call = mock_event_bus.emit.call_args_list[1]
        assert completed_call[0][0] == TASK_COMPLETED
        completed_payload = completed_call[0][1]
        assert completed_payload["task_id"] == sample_task.id
        assert completed_payload["run_id"] == run.id
        assert completed_payload["task_name"] == sample_task.name
        assert completed_payload["exit_code"] == 0
        assert completed_payload["duration_ms"] == run.duration_ms
        assert "timestamp" in completed_payload

    def test_execute_task_emits_failed_event(
        self, db_session: Session, sample_task: Task
    ) -> None:
        """Test that failed task execution emits TASK_STARTED and TASK_FAILED events."""
        # Arrange
        sample_task.command = "exit 42"
        mock_event_bus = MagicMock()

        # Act
        with patch("taskmanager.executor.get_event_bus", return_value=mock_event_bus):
            run = execute_task(sample_task, db_session)

        # Assert
        assert run.status == RunStatus.FAILED
        assert run.exit_code == 42
        assert mock_event_bus.emit.call_count == 2

        # Verify TASK_STARTED event
        started_call = mock_event_bus.emit.call_args_list[0]
        assert started_call[0][0] == TASK_STARTED

        # Verify TASK_FAILED event
        failed_call = mock_event_bus.emit.call_args_list[1]
        assert failed_call[0][0] == TASK_FAILED
        failed_payload = failed_call[0][1]
        assert failed_payload["task_id"] == sample_task.id
        assert failed_payload["run_id"] == run.id
        assert failed_payload["task_name"] == sample_task.name
        assert failed_payload["exit_code"] == 42
        assert failed_payload["duration_ms"] == run.duration_ms
        assert "timestamp" in failed_payload

    def test_execute_task_emits_timeout_event(
        self, db_session: Session, sample_task: Task
    ) -> None:
        """Test that timeout execution emits TASK_STARTED and TASK_TIMEOUT events."""
        # Arrange
        sample_task.command = "sleep 10"
        mock_event_bus = MagicMock()

        def mock_subprocess_run(*args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0] if args else "", timeout=1)

        # Act
        with (
            patch("taskmanager.executor.get_event_bus", return_value=mock_event_bus),
            patch("taskmanager.executor.subprocess.run", side_effect=mock_subprocess_run),
        ):
            run = execute_task(sample_task, db_session)

        # Assert
        assert run.status == RunStatus.FAILED
        assert run.error_message is not None
        assert "timed out" in run.error_message.lower()
        assert mock_event_bus.emit.call_count == 2

        # Verify TASK_STARTED event
        started_call = mock_event_bus.emit.call_args_list[0]
        assert started_call[0][0] == TASK_STARTED

        # Verify TASK_TIMEOUT event
        timeout_call = mock_event_bus.emit.call_args_list[1]
        assert timeout_call[0][0] == TASK_TIMEOUT
        timeout_payload = timeout_call[0][1]
        assert timeout_payload["task_id"] == sample_task.id
        assert timeout_payload["run_id"] == run.id
        assert timeout_payload["task_name"] == sample_task.name
        assert timeout_payload["duration_ms"] == run.duration_ms
        assert "timeout_seconds" in timeout_payload
        assert "timestamp" in timeout_payload

    def test_execute_inline_emits_events_with_none_task_id(
        self, db_session: Session
    ) -> None:
        """Test that inline execution emits events with task_id=None and task_name='<inline>'."""
        # Arrange
        mock_event_bus = MagicMock()

        # Act
        with patch("taskmanager.executor.get_event_bus", return_value=mock_event_bus):
            run = execute_inline("echo test", db_session)

        # Assert
        assert run.status == RunStatus.SUCCESS
        assert run.task_id is None
        assert mock_event_bus.emit.call_count == 2

        # Verify TASK_STARTED event
        started_call = mock_event_bus.emit.call_args_list[0]
        assert started_call[0][0] == TASK_STARTED
        started_payload = started_call[0][1]
        assert started_payload["task_id"] is None
        assert started_payload["task_name"] == "<inline>"
        assert started_payload["run_id"] == run.id

        # Verify TASK_COMPLETED event
        completed_call = mock_event_bus.emit.call_args_list[1]
        assert completed_call[0][0] == TASK_COMPLETED
        completed_payload = completed_call[0][1]
        assert completed_payload["task_id"] is None
        assert completed_payload["task_name"] == "<inline>"
        assert completed_payload["run_id"] == run.id
        assert completed_payload["exit_code"] == 0


class TestPluginIntegration:
    """Tests for plugin hook integration in executor."""

    def test_plugin_veto_cancels_execution(
        self, db_session: Session, sample_task: Task
    ) -> None:
        """Test that plugin returning False vetoes execution and sets status to CANCELLED."""
        # Arrange
        sample_task.command = "echo should not run"

        # Create a mock plugin that vetoes execution
        class VetoPlugin:
            def on_before_execute(self, task: Task, run: Run) -> bool:
                return False  # Veto execution

        # Act
        with patch("taskmanager.executor.PluginManager") as mock_pm_class:
            mock_pm = MagicMock()
            mock_pm.call_on_before_execute.return_value = False
            mock_pm_class.return_value = mock_pm

            run = execute_task(sample_task, db_session)

        # Assert
        assert run.status == RunStatus.CANCELLED
        assert run.started_at is not None
        assert run.finished_at is not None
        assert run.exit_code is None  # Never executed
        assert run.stdout == ""  # Never executed (default value)
        assert run.stderr == ""  # Never executed (default value)
        assert run.duration_ms is None  # Never executed
        assert mock_pm.call_on_before_execute.call_count == 1

    def test_plugin_allows_execution(
        self, db_session: Session, sample_task: Task
    ) -> None:
        """Test that plugin returning True allows execution."""
        # Arrange
        sample_task.command = "echo allowed"

        # Act
        with patch("taskmanager.executor.PluginManager") as mock_pm_class:
            mock_pm = MagicMock()
            mock_pm.call_on_before_execute.return_value = True
            mock_pm_class.return_value = mock_pm

            run = execute_task(sample_task, db_session)

        # Assert
        assert run.status == RunStatus.SUCCESS
        assert run.exit_code == 0
        assert "allowed" in run.stdout
        assert mock_pm.call_on_before_execute.call_count == 1
        assert mock_pm.call_on_after_execute.call_count == 1

    def test_after_execute_hook_receives_completed_run(
        self, db_session: Session, sample_task: Task
    ) -> None:
        """Test that on_after_execute receives completed Run with all fields."""
        # Arrange
        sample_task.command = "echo test"

        # Act
        with patch("taskmanager.executor.PluginManager") as mock_pm_class:
            mock_pm = MagicMock()
            mock_pm.call_on_before_execute.return_value = True
            mock_pm_class.return_value = mock_pm

            execute_task(sample_task, db_session)

        # Assert - verify the hook was called
        assert mock_pm.call_on_after_execute.call_count == 1

        # Extract the actual arguments passed to the hook
        call_args = mock_pm.call_on_after_execute.call_args
        # call_args is a tuple: (args, kwargs) or use args[0] and args[1]
        passed_task = call_args[0][0]  # First positional argument
        passed_run = call_args[0][1]   # Second positional argument

        # Verify the task and run were passed correctly
        assert passed_task == sample_task

        # Verify the Run has all completion fields
        assert passed_run.status == RunStatus.SUCCESS
        assert passed_run.exit_code == 0
        assert passed_run.stdout is not None
        assert passed_run.stderr is not None
        assert passed_run.duration_ms is not None
        assert passed_run.started_at is not None
        assert passed_run.finished_at is not None

    def test_after_execute_called_on_failure(
        self, db_session: Session, sample_task: Task
    ) -> None:
        """Test that on_after_execute is called even when task fails."""
        # Arrange
        sample_task.command = "exit 1"

        # Act
        with patch("taskmanager.executor.PluginManager") as mock_pm_class:
            mock_pm = MagicMock()
            mock_pm.call_on_before_execute.return_value = True
            mock_pm_class.return_value = mock_pm

            run = execute_task(sample_task, db_session)

        # Assert
        assert run.status == RunStatus.FAILED
        assert run.exit_code == 1
        assert mock_pm.call_on_after_execute.call_count == 1

    def test_after_execute_called_on_timeout(
        self, db_session: Session, sample_task: Task
    ) -> None:
        """Test that on_after_execute is called even on timeout."""
        # Arrange
        sample_task.command = "sleep 10"

        def mock_subprocess_run(*args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0] if args else "", timeout=1)

        # Act
        with (
            patch("taskmanager.executor.PluginManager") as mock_pm_class,
            patch("taskmanager.executor.subprocess.run", side_effect=mock_subprocess_run),
        ):
            mock_pm = MagicMock()
            mock_pm.call_on_before_execute.return_value = True
            mock_pm_class.return_value = mock_pm

            run = execute_task(sample_task, db_session)

        # Assert
        assert run.status == RunStatus.FAILED
        assert "timed out" in run.error_message.lower()
        assert mock_pm.call_on_after_execute.call_count == 1

    def test_plugin_exception_in_before_execute_allows_execution(
        self, db_session: Session, sample_task: Task
    ) -> None:
        """Test that exceptions in PluginManager.call_on_before_execute allow execution.

        When PluginManager encounters an exception, it logs the error and returns True
        to allow execution to proceed safely.
        """
        # Arrange
        sample_task.command = "echo test"

        # Create a real PluginManager with a failing plugin
        from taskmanager.plugins import PluginManager

        class PluginCrashError(Exception):
            """Custom exception for testing plugin failures."""

            def __init__(self) -> None:
                super().__init__("Plugin crashed")

        class FailingPlugin:
            def on_before_execute(self, task: Task, run: Run) -> bool:
                raise PluginCrashError

        # Act - register a plugin that will crash, then execute task
        # Patch PluginManager's initialization to avoid loading real plugins
        with patch.object(PluginManager, "_discover_and_load_plugins"):
            pm = PluginManager()
            pm.register_plugin(FailingPlugin(), "test-plugin")

            # Now patch the executor to use our configured PluginManager
            with patch("taskmanager.executor.PluginManager", return_value=pm):
                run = execute_task(sample_task, db_session)

        # Assert - execution should proceed despite plugin exception
        assert run.status == RunStatus.SUCCESS
        assert run.exit_code == 0
        assert "test" in run.stdout

    def test_plugin_exception_in_after_execute_does_not_crash(
        self, db_session: Session, sample_task: Task
    ) -> None:
        """Test that exceptions in on_after_execute don't crash the executor."""
        # Arrange
        sample_task.command = "echo test"

        # Create a real PluginManager with a failing after_execute plugin
        from taskmanager.plugins import PluginManager

        class AfterExecuteCrashError(Exception):
            """Custom exception for testing after_execute failures."""

            def __init__(self) -> None:
                super().__init__("After execute crashed")

        class FailingAfterPlugin:
            def on_after_execute(self, task: Task, run: Run) -> None:
                raise AfterExecuteCrashError

        # Act
        with patch.object(PluginManager, "_discover_and_load_plugins"):
            pm = PluginManager()
            pm.register_plugin(FailingAfterPlugin(), "test-plugin")

            with patch("taskmanager.executor.PluginManager", return_value=pm):
                run = execute_task(sample_task, db_session)

        # Assert - execution should complete successfully
        assert run.status == RunStatus.SUCCESS
        assert run.exit_code == 0
        assert "test" in run.stdout
