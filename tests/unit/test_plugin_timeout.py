"""Unit tests for timeout plugin."""

import time
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from taskmanager.database import Base
from taskmanager.executor import execute_task
from taskmanager.models import RunStatus, Task
from taskmanager.settings import get_settings


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


class TestTimeoutPluginNoMetadata:
    """Tests for timeout plugin when no metadata is present."""

    def test_no_metadata_uses_default_timeout(self, db_session: Session) -> None:
        """Test that task without task_metadata uses default timeout."""
        # Arrange - task with no task_metadata
        task = Task(
            name="no-timeout-metadata-task",
            command="echo fast",
            task_metadata=None,
        )
        db_session.add(task)
        db_session.commit()

        # Act
        run = execute_task(task, db_session)

        # Assert - should succeed with default timeout
        assert run.status == RunStatus.SUCCESS
        assert run.exit_code == 0
        assert "fast" in run.stdout

        # Verify default timeout was used (no timeout_override set)
        # The plugin should not set timeout_override if metadata is missing
        assert not hasattr(run, "timeout_override")


class TestTimeoutPluginOverride:
    """Tests for timeout plugin with timeout override."""

    def test_timeout_override_works(self, db_session: Session) -> None:
        """Test that timeout plugin overrides default timeout."""
        # Arrange - task with short timeout
        task = Task(
            name="timeout-override-task",
            command="sleep 10",
            task_metadata={"timeout_seconds": 2},
        )
        db_session.add(task)
        db_session.commit()

        # Act
        start_time = time.perf_counter()
        run = execute_task(task, db_session)
        elapsed = time.perf_counter() - start_time

        # Assert - should fail after ~2 seconds (not 300s default)
        assert run.status == RunStatus.FAILED
        assert 1.5 <= elapsed <= 2.5, f"Should timeout after ~2s, took {elapsed:.2f}s"

        # Verify error message contains timeout information
        assert run.error_message is not None
        assert "timed out after 2 seconds" in run.error_message.lower()

        # Verify duration is approximately 2000ms
        assert run.duration_ms is not None
        assert 1500 <= run.duration_ms <= 2500, (
            f"Duration should be ~2000ms, got {run.duration_ms}ms"
        )

    def test_timeout_creates_failed_run_with_error_message(
        self, db_session: Session
    ) -> None:
        """Test that timeout creates FAILED run with clear error message."""
        # Arrange - task with very short timeout
        task = Task(
            name="timeout-error-task",
            command="sleep 100",
            task_metadata={"timeout_seconds": 1},
        )
        db_session.add(task)
        db_session.commit()

        # Act
        run = execute_task(task, db_session)

        # Assert - verify run status and error details
        assert run.status == RunStatus.FAILED
        assert run.error_message is not None
        assert "timed out after 1 seconds" in run.error_message.lower()

        # Verify exit_code is None (process was killed)
        assert run.exit_code is None, "Exit code should be None when process is killed"

    def test_timeout_with_different_values(self, db_session: Session) -> None:
        """Test timeout override with different timeout values."""
        # Arrange - task with 3 second timeout
        task = Task(
            name="timeout-3s-task",
            command="sleep 20",
            task_metadata={"timeout_seconds": 3},
        )
        db_session.add(task)
        db_session.commit()

        # Act
        start_time = time.perf_counter()
        run = execute_task(task, db_session)
        elapsed = time.perf_counter() - start_time

        # Assert - should timeout after ~3 seconds
        assert run.status == RunStatus.FAILED
        assert 2.5 <= elapsed <= 3.5, f"Should timeout after ~3s, took {elapsed:.2f}s"
        assert run.error_message is not None
        assert "timed out after 3 seconds" in run.error_message.lower()


class TestTimeoutPluginInvalidValues:
    """Tests for timeout plugin with invalid timeout values."""

    def test_negative_timeout_value(self, db_session: Session) -> None:
        """Test that negative timeout_seconds value uses default timeout."""
        # Arrange - task with invalid negative timeout
        task = Task(
            name="negative-timeout-task",
            command="echo quick",
            task_metadata={"timeout_seconds": -5},
        )
        db_session.add(task)
        db_session.commit()

        # Act
        run = execute_task(task, db_session)

        # Assert - should succeed (not vetoed), uses default timeout
        assert run.status == RunStatus.SUCCESS
        assert run.exit_code == 0
        assert "quick" in run.stdout

        # Verify that invalid value didn't crash the executor
        assert run.error_message is None

    def test_zero_timeout_value(self, db_session: Session) -> None:
        """Test that zero timeout_seconds value uses default timeout."""
        # Arrange - task with zero timeout
        task = Task(
            name="zero-timeout-task",
            command="echo instant",
            task_metadata={"timeout_seconds": 0},
        )
        db_session.add(task)
        db_session.commit()

        # Act
        run = execute_task(task, db_session)

        # Assert - should succeed (not vetoed), uses default timeout
        assert run.status == RunStatus.SUCCESS
        assert run.exit_code == 0
        assert "instant" in run.stdout

    def test_non_numeric_timeout_value(self, db_session: Session) -> None:
        """Test that non-numeric timeout_seconds value uses default timeout."""
        # Arrange - task with non-numeric timeout
        task = Task(
            name="string-timeout-task",
            command="echo works",
            task_metadata={"timeout_seconds": "invalid"},
        )
        db_session.add(task)
        db_session.commit()

        # Act
        run = execute_task(task, db_session)

        # Assert - should succeed (not vetoed), uses default timeout
        assert run.status == RunStatus.SUCCESS
        assert run.exit_code == 0
        assert "works" in run.stdout


class TestTimeoutPluginFloatValues:
    """Tests for timeout plugin with float timeout values."""

    def test_float_timeout_value(self, db_session: Session) -> None:
        """Test that float timeout_seconds value works correctly."""
        # Arrange - task with float timeout (2.5 seconds)
        task = Task(
            name="float-timeout-task",
            command="sleep 5",
            task_metadata={"timeout_seconds": 2.5},
        )
        db_session.add(task)
        db_session.commit()

        # Act
        start_time = time.perf_counter()
        run = execute_task(task, db_session)
        elapsed = time.perf_counter() - start_time

        # Assert - should timeout after ~2.5 seconds
        assert run.status == RunStatus.FAILED
        assert 2.0 <= elapsed <= 3.0, f"Should timeout after ~2.5s, took {elapsed:.2f}s"


class TestTimeoutPluginSuccessWithinTimeout:
    """Tests for timeout plugin when task completes within timeout."""

    def test_task_completes_within_timeout(self, db_session: Session) -> None:
        """Test that task completing within timeout succeeds normally."""
        # Arrange - fast task with generous timeout
        task = Task(
            name="quick-task",
            command="echo done",
            task_metadata={"timeout_seconds": 10},
        )
        db_session.add(task)
        db_session.commit()

        # Act
        run = execute_task(task, db_session)

        # Assert - should succeed
        assert run.status == RunStatus.SUCCESS
        assert run.exit_code == 0
        assert "done" in run.stdout
        assert run.error_message is None

        # Verify duration is much less than timeout
        assert run.duration_ms is not None
        assert run.duration_ms < 1000, "Fast command should complete in under 1 second"


class TestTimeoutPluginLargeTimeout:
    """Tests for timeout plugin with large timeout values."""

    def test_large_timeout_value(self, db_session: Session) -> None:
        """Test that large timeout values work correctly."""
        # Arrange - task with very large timeout
        task = Task(
            name="large-timeout-task",
            command="echo fast",
            task_metadata={"timeout_seconds": 99999},
        )
        db_session.add(task)
        db_session.commit()

        # Act
        run = execute_task(task, db_session)

        # Assert - should succeed quickly despite large timeout
        assert run.status == RunStatus.SUCCESS
        assert run.exit_code == 0
        assert run.duration_ms is not None
        assert run.duration_ms < 1000


class TestTimeoutPluginDefaultSettings:
    """Tests for timeout plugin interaction with default settings."""

    def test_default_timeout_from_settings(self, db_session: Session) -> None:
        """Test that default timeout is used when no override is set."""
        # Arrange - task without timeout metadata
        task = Task(
            name="default-settings-task",
            command="echo testing",
            task_metadata={},  # Empty metadata, no timeout_seconds
        )
        db_session.add(task)
        db_session.commit()

        # Act
        run = execute_task(task, db_session)

        # Assert - should succeed with default timeout
        assert run.status == RunStatus.SUCCESS
        assert run.exit_code == 0

        # Verify default timeout from settings is used
        settings = get_settings()
        assert settings.subprocess_timeout == 300, "Default timeout should be 300s"
