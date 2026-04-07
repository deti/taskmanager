"""Unit tests for retry plugin."""

import time
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from taskmanager.database import Base
from taskmanager.executor import execute_task
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


class TestRetryPluginNoMetadata:
    """Tests for retry plugin when no metadata is present."""

    def test_no_metadata_no_retry(self, db_session: Session, tmp_path: Path) -> None:
        """Test that task without task_metadata fails once and stops."""
        # Arrange - task with no task_metadata
        task = Task(
            name="no-metadata-task",
            command="exit 1",  # Always fails
            task_metadata=None,
        )
        db_session.add(task)
        db_session.commit()

        # Act
        run = execute_task(task, db_session)

        # Assert - only 1 Run record created
        assert run.status == RunStatus.FAILED
        assert run.exit_code == 1

        total_runs = db_session.query(Run).filter_by(task_id=task.id).count()
        assert total_runs == 1, "Should create only 1 Run record without retry metadata"


class TestRetryPluginSuccessAfterRetries:
    """Tests for retry plugin with eventual success."""

    def test_retry_with_success_after_2_attempts(
        self, db_session: Session, tmp_path: Path
    ) -> None:
        """Test task with retry_count=3, command fails 2 times then succeeds."""
        # Arrange - create a counter file pattern for flaky command
        counter_file = tmp_path / "counter.txt"
        command = f"""
if [ ! -f {counter_file} ]; then
    echo 0 > {counter_file}
fi
count=$(cat {counter_file})
echo $((count + 1)) > {counter_file}
if [ $count -lt 2 ]; then
    exit 1
else
    exit 0
fi
"""
        task = Task(
            name="retry-success-task",
            command=command,
            task_metadata={"retry_count": 3},
            shell="/bin/bash",
        )
        db_session.add(task)
        db_session.commit()

        # Act
        start_time = time.perf_counter()
        execute_task(task, db_session)
        elapsed = time.perf_counter() - start_time

        # Assert - verify 3 Run records total (2 failed, 1 success)
        all_runs = (
            db_session.query(Run)
            .filter_by(task_id=task.id)
            .order_by(Run.started_at)
            .all()
        )
        assert len(all_runs) == 3, "Should create 3 Run records (1 initial + 2 retries)"

        # First two runs should be FAILED
        assert all_runs[0].status == RunStatus.FAILED
        assert all_runs[0].exit_code == 1
        assert all_runs[1].status == RunStatus.FAILED
        assert all_runs[1].exit_code == 1

        # Last run should be SUCCESS
        assert all_runs[2].status == RunStatus.SUCCESS
        assert all_runs[2].exit_code == 0

        # Verify exponential backoff timing (1s + 2s = 3s minimum)
        # First retry: 1s, second retry: 2s
        assert elapsed >= 3.0, f"Should take at least 3s (1s + 2s backoff), took {elapsed:.2f}s"
        assert elapsed < 5.0, f"Should take less than 5s, took {elapsed:.2f}s"

    def test_each_retry_creates_new_run_linked_to_same_task(
        self, db_session: Session, tmp_path: Path
    ) -> None:
        """Test that each retry creates a new Run record linked to the same task."""
        # Arrange - counter file pattern
        counter_file = tmp_path / "counter2.txt"
        command = f"""
if [ ! -f {counter_file} ]; then
    echo 0 > {counter_file}
fi
count=$(cat {counter_file})
echo $((count + 1)) > {counter_file}
if [ $count -lt 1 ]; then
    exit 1
else
    exit 0
fi
"""
        task = Task(
            name="retry-linkage-task",
            command=command,
            task_metadata={"retry_count": 2},
            shell="/bin/bash",
        )
        db_session.add(task)
        db_session.commit()

        # Act
        execute_task(task, db_session)

        # Assert - verify all Run records have same task_id but unique ids
        all_runs = db_session.query(Run).filter_by(task_id=task.id).all()
        assert len(all_runs) == 2, "Should create 2 Run records (1 initial + 1 retry)"

        # All runs have same task_id
        assert all(run.task_id == task.id for run in all_runs)

        # Each run has unique id
        run_ids = [run.id for run in all_runs]
        assert len(run_ids) == len(set(run_ids)), "Each Run should have unique ID"


class TestRetryPluginMaxRetriesExhausted:
    """Tests for retry plugin when max retries are exhausted."""

    def test_max_retries_exhausted(self, db_session: Session) -> None:
        """Test task with retry_count=2, command always fails."""
        # Arrange - command that always fails
        task = Task(
            name="retry-exhausted-task",
            command="exit 1",
            task_metadata={"retry_count": 2},
        )
        db_session.add(task)
        db_session.commit()

        # Act
        start_time = time.perf_counter()
        execute_task(task, db_session)
        elapsed = time.perf_counter() - start_time

        # Assert - verify 3 Run records total (initial + 2 retries, all failed)
        all_runs = db_session.query(Run).filter_by(task_id=task.id).all()
        assert len(all_runs) == 3, "Should create 3 Run records (1 initial + 2 retries)"

        # All runs should be FAILED
        for run_record in all_runs:
            assert run_record.status == RunStatus.FAILED
            assert run_record.exit_code == 1

        # Final Run status is FAILED
        final_run = all_runs[-1]
        assert final_run.status == RunStatus.FAILED

        # Verify exponential backoff timing (1s + 2s = 3s minimum)
        assert elapsed >= 3.0, f"Should take at least 3s (1s + 2s backoff), took {elapsed:.2f}s"
        assert elapsed < 5.0, f"Should take less than 5s, took {elapsed:.2f}s"


class TestRetryPluginExponentialBackoff:
    """Tests for retry plugin exponential backoff timing."""

    def test_exponential_backoff_timing(self, db_session: Session, tmp_path: Path) -> None:
        """Test that retry delays follow exponential backoff: 1s, 2s, 4s."""
        # Arrange - counter file pattern that fails 3 times
        counter_file = tmp_path / "counter3.txt"
        command = f"""
if [ ! -f {counter_file} ]; then
    echo 0 > {counter_file}
fi
count=$(cat {counter_file})
echo $((count + 1)) > {counter_file}
if [ $count -lt 3 ]; then
    exit 1
else
    exit 0
fi
"""
        task = Task(
            name="retry-backoff-task",
            command=command,
            task_metadata={"retry_count": 3},
            shell="/bin/bash",
        )
        db_session.add(task)
        db_session.commit()

        # Act
        start_time = time.perf_counter()
        execute_task(task, db_session)
        elapsed = time.perf_counter() - start_time

        # Assert - verify timing
        # First retry: 1s (2^0), second retry: 2s (2^1), third retry: 4s (2^2)
        # Total: 1 + 2 + 4 = 7s minimum
        expected_min = 7.0
        expected_max = 9.0  # Allow some tolerance
        assert elapsed >= expected_min, (
            f"Should take at least {expected_min}s (1s + 2s + 4s backoff), "
            f"took {elapsed:.2f}s"
        )
        assert elapsed < expected_max, (
            f"Should take less than {expected_max}s, took {elapsed:.2f}s"
        )

        # Verify 4 Run records (1 initial + 3 retries)
        all_runs = db_session.query(Run).filter_by(task_id=task.id).all()
        assert len(all_runs) == 4, "Should create 4 Run records (1 initial + 3 retries)"


class TestRetryPluginZeroRetries:
    """Tests for retry plugin with zero retries configured."""

    def test_zero_retry_count_no_retry(self, db_session: Session) -> None:
        """Test that retry_count=0 does not retry."""
        # Arrange
        task = Task(
            name="zero-retry-task",
            command="exit 1",
            task_metadata={"retry_count": 0},
        )
        db_session.add(task)
        db_session.commit()

        # Act
        run = execute_task(task, db_session)

        # Assert - only 1 Run record created
        assert run.status == RunStatus.FAILED
        total_runs = db_session.query(Run).filter_by(task_id=task.id).count()
        assert total_runs == 1, "Should create only 1 Run record with retry_count=0"


class TestRetryPluginSuccessOnFirstAttempt:
    """Tests for retry plugin when task succeeds on first attempt."""

    def test_success_on_first_attempt_no_retry(self, db_session: Session) -> None:
        """Test that successful task is not retried even with retry_count set."""
        # Arrange
        task = Task(
            name="first-success-task",
            command="echo success",
            task_metadata={"retry_count": 3},
        )
        db_session.add(task)
        db_session.commit()

        # Act
        run = execute_task(task, db_session)

        # Assert - only 1 Run record created, no retries
        assert run.status == RunStatus.SUCCESS
        assert run.exit_code == 0
        total_runs = db_session.query(Run).filter_by(task_id=task.id).count()
        assert total_runs == 1, "Should not retry successful tasks"
