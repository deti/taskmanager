"""Unit tests for task executor."""

import subprocess
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from taskmanager.database import Base
from taskmanager.executor import execute_task
from taskmanager.models import Run, RunStatus, Task


@pytest.fixture
def db_session() -> Session:
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
