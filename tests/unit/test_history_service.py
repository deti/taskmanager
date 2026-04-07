"""Unit tests for history service layer.

Tests all pruning and statistics operations using in-memory SQLite database.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from taskmanager.database import Base
from taskmanager.models import Run, RunStatus, Task
from taskmanager.services.history_service import get_stats, prune_runs
from taskmanager.settings import Settings


@pytest.fixture
def db_session() -> Session:
    """Create an in-memory SQLite session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)
    session = session_local()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture
def sample_tasks(db_session: Session) -> list[Task]:
    """Create sample tasks for testing."""
    tasks = [
        Task(name="task-alpha", command="echo alpha"),
        Task(name="task-beta", command="echo beta"),
        Task(name="task-gamma", command="echo gamma"),
        Task(name="task-delta", command="echo delta"),
    ]
    db_session.add_all(tasks)
    db_session.flush()
    return tasks


@pytest.fixture
def seed_runs(db_session: Session, sample_tasks: list[Task]) -> list[Run]:
    """Seed 100 runs across multiple tasks with varied statuses and dates."""
    runs = []
    base_date = datetime(2026, 4, 8, tzinfo=UTC)

    # Task alpha: 30 runs (20 success, 5 failed, 5 running) over 60 days
    for i in range(30):
        status = (
            RunStatus.SUCCESS
            if i < 20
            else RunStatus.FAILED if i < 25 else RunStatus.RUNNING
        )
        started_at = base_date - timedelta(days=i * 2)
        duration_ms = 1000 + (i * 50) if i < 25 else None  # No duration for running
        run = Run(
            task_id=sample_tasks[0].id,
            command_snapshot="echo alpha",
            status=status,
            started_at=started_at,
            finished_at=started_at + timedelta(seconds=1) if i < 25 else None,
            duration_ms=duration_ms,
            exit_code=0 if status == RunStatus.SUCCESS else 1 if i < 25 else None,
        )
        runs.append(run)

    # Task beta: 25 runs (15 success, 10 failed) over 50 days
    for i in range(25):
        status = RunStatus.SUCCESS if i < 15 else RunStatus.FAILED
        started_at = base_date - timedelta(days=i * 2)
        duration_ms = 800 + (i * 30)
        run = Run(
            task_id=sample_tasks[1].id,
            command_snapshot="echo beta",
            status=status,
            started_at=started_at,
            finished_at=started_at + timedelta(seconds=1),
            duration_ms=duration_ms,
            exit_code=0 if status == RunStatus.SUCCESS else 1,
        )
        runs.append(run)

    # Task gamma: 20 runs (18 success, 2 failed) over 40 days
    for i in range(20):
        status = RunStatus.SUCCESS if i < 18 else RunStatus.FAILED
        started_at = base_date - timedelta(days=i * 2)
        duration_ms = 500 + (i * 20)
        run = Run(
            task_id=sample_tasks[2].id,
            command_snapshot="echo gamma",
            status=status,
            started_at=started_at,
            finished_at=started_at + timedelta(seconds=1),
            duration_ms=duration_ms,
            exit_code=0 if status == RunStatus.SUCCESS else 1,
        )
        runs.append(run)

    # Task delta: 25 runs (all success) over 50 days
    for i in range(25):
        started_at = base_date - timedelta(days=i * 2)
        duration_ms = 1200 + (i * 40)
        run = Run(
            task_id=sample_tasks[3].id,
            command_snapshot="echo delta",
            status=RunStatus.SUCCESS,
            started_at=started_at,
            finished_at=started_at + timedelta(seconds=1),
            duration_ms=duration_ms,
            exit_code=0,
        )
        runs.append(run)

    db_session.add_all(runs)
    db_session.commit()
    return runs


class TestPruneRuns:
    """Tests for prune_runs function."""

    def test_prune_runs_with_default_retention(
        self, db_session: Session, seed_runs: list[Run]
    ) -> None:
        """Test pruning runs using default retention days from settings."""
        # Mock settings to return 30 days retention
        mock_settings = Settings(history_retention_days=30)

        with patch("taskmanager.services.history_service.get_settings") as mock:
            mock.return_value = mock_settings

            # Count runs before pruning
            initial_count = len(seed_runs)
            assert initial_count == 100

            # Prune with default retention (30 days)
            deleted_count = prune_runs(db_session)

            # Verify runs were deleted
            assert deleted_count > 0

            # Verify remaining runs are within retention period
            # SQLite strips timezone info, so use naive datetime for comparison
            cutoff_date = datetime.now(UTC) - timedelta(days=30)
            cutoff_date_naive = cutoff_date.replace(tzinfo=None)
            remaining_runs = db_session.query(Run).all()
            for run in remaining_runs:
                assert run.started_at >= cutoff_date_naive

    def test_prune_runs_with_custom_older_than_days(
        self, db_session: Session, seed_runs: list[Run]
    ) -> None:
        """Test pruning runs with custom older_than_days parameter."""
        # Prune runs older than 45 days
        deleted_count = prune_runs(db_session, older_than_days=45)

        # Verify runs were deleted
        assert deleted_count > 0

        # Verify remaining runs are within 45 days
        # SQLite strips timezone info, so use naive datetime for comparison
        cutoff_date = datetime.now(UTC) - timedelta(days=45)
        cutoff_date_naive = cutoff_date.replace(tzinfo=None)
        remaining_runs = db_session.query(Run).all()
        for run in remaining_runs:
            assert run.started_at >= cutoff_date_naive

    def test_prune_runs_dry_run_no_deletion(
        self, db_session: Session, seed_runs: list[Run]
    ) -> None:
        """Test dry-run mode counts without deleting."""
        initial_count = db_session.query(Run).count()
        assert initial_count == 100

        # Dry-run with 30 days retention
        would_delete_count = prune_runs(db_session, older_than_days=30, dry_run=True)

        # Verify count was returned but no deletion occurred
        assert would_delete_count > 0
        final_count = db_session.query(Run).count()
        assert final_count == initial_count  # No change

    def test_prune_runs_respects_cutoff_boundary(
        self, db_session: Session, sample_tasks: list[Task]
    ) -> None:
        """Test that prune_runs respects the cutoff date boundary exactly."""
        # Create runs at specific dates relative to now
        # Use a fixed reference time to avoid microsecond precision issues
        now = datetime.now(UTC).replace(microsecond=0)
        runs = [
            # Run 29 days old (should NOT be deleted with 30-day retention)
            Run(
                task_id=sample_tasks[0].id,
                command_snapshot="echo 1",
                status=RunStatus.SUCCESS,
                started_at=now - timedelta(days=29),
                duration_ms=1000,
            ),
            # Run 29.5 days old (should NOT be deleted)
            Run(
                task_id=sample_tasks[0].id,
                command_snapshot="echo 2",
                status=RunStatus.SUCCESS,
                started_at=now - timedelta(days=29, hours=12),
                duration_ms=1000,
            ),
            # Run 30.5 days old (SHOULD be deleted - older than cutoff)
            Run(
                task_id=sample_tasks[0].id,
                command_snapshot="echo 3",
                status=RunStatus.SUCCESS,
                started_at=now - timedelta(days=30, hours=12),
                duration_ms=1000,
            ),
            # Run 31 days old (SHOULD be deleted)
            Run(
                task_id=sample_tasks[0].id,
                command_snapshot="echo 4",
                status=RunStatus.SUCCESS,
                started_at=now - timedelta(days=31),
                duration_ms=1000,
            ),
        ]
        db_session.add_all(runs)
        db_session.commit()

        # Prune with 30 days retention
        deleted_count = prune_runs(db_session, older_than_days=30)

        # Should delete exactly 2 runs (30.5d and 31d)
        assert deleted_count == 2

        # Verify correct runs remain
        remaining_runs = db_session.query(Run).all()
        assert len(remaining_runs) == 2

    def test_prune_runs_empty_database(self, db_session: Session) -> None:
        """Test pruning on empty database returns zero."""
        deleted_count = prune_runs(db_session, older_than_days=30)
        assert deleted_count == 0


class TestGetStats:
    """Tests for get_stats function."""

    def test_get_stats_global(
        self, db_session: Session, seed_runs: list[Run], sample_tasks: list[Task]
    ) -> None:
        """Test global statistics across all tasks."""
        stats = get_stats(db_session)

        # Verify total runs
        assert stats["total_runs"] == 100

        # Verify success rate
        # Task alpha: 20 success, 5 failed, 5 running (20 success)
        # Task beta: 15 success, 10 failed (15 success)
        # Task gamma: 18 success, 2 failed (18 success)
        # Task delta: 25 success (25 success)
        # Total: 78 success out of 100 = 78%
        assert stats["success_rate"] == 78.0

        # Verify avg duration is calculated
        assert stats["avg_duration_ms"] is not None
        assert stats["avg_duration_ms"] > 0

        # Verify most_failed_tasks is populated
        assert len(stats["most_failed_tasks"]) > 0

        # Task beta should be the most failed (10 failures)
        most_failed = stats["most_failed_tasks"][0]
        assert most_failed["task_name"] == "task-beta"
        assert most_failed["failure_count"] == 10

    def test_get_stats_per_task(
        self, db_session: Session, seed_runs: list[Run], sample_tasks: list[Task]
    ) -> None:
        """Test per-task statistics."""
        # Get stats for task-alpha
        stats = get_stats(db_session, task_id=sample_tasks[0].id)

        # Task alpha has 30 runs (20 success, 5 failed, 5 running)
        assert stats["total_runs"] == 30
        assert stats["success_rate"] == pytest.approx(66.67, abs=0.1)  # 20/30 * 100
        assert stats["avg_duration_ms"] is not None

        # most_failed_tasks should be empty for per-task stats
        assert stats["most_failed_tasks"] == []

    def test_get_stats_empty_database(self, db_session: Session) -> None:
        """Test statistics on empty database."""
        stats = get_stats(db_session)

        assert stats["total_runs"] == 0
        assert stats["success_rate"] == 0.0
        assert stats["avg_duration_ms"] is None
        assert stats["most_failed_tasks"] == []

    def test_get_stats_all_success(
        self, db_session: Session, sample_tasks: list[Task]
    ) -> None:
        """Test statistics when all runs are successful."""
        # Create 10 successful runs
        runs = [
            Run(
                task_id=sample_tasks[0].id,
                command_snapshot=f"echo {i}",
                status=RunStatus.SUCCESS,
                started_at=datetime.now(UTC) - timedelta(days=i),
                duration_ms=1000,
            )
            for i in range(10)
        ]
        db_session.add_all(runs)
        db_session.commit()

        stats = get_stats(db_session)

        assert stats["total_runs"] == 10
        assert stats["success_rate"] == 100.0
        assert stats["avg_duration_ms"] == 1000.0
        assert stats["most_failed_tasks"] == []  # No failures

    def test_get_stats_all_failed(
        self, db_session: Session, sample_tasks: list[Task]
    ) -> None:
        """Test statistics when all runs failed."""
        # Create 10 failed runs
        runs = [
            Run(
                task_id=sample_tasks[0].id,
                command_snapshot=f"echo {i}",
                status=RunStatus.FAILED,
                started_at=datetime.now(UTC) - timedelta(days=i),
                duration_ms=1000,
            )
            for i in range(10)
        ]
        db_session.add_all(runs)
        db_session.commit()

        stats = get_stats(db_session)

        assert stats["total_runs"] == 10
        assert stats["success_rate"] == 0.0
        assert stats["avg_duration_ms"] == 1000.0

        # Should have task-alpha as most failed
        assert len(stats["most_failed_tasks"]) == 1
        assert stats["most_failed_tasks"][0]["task_name"] == "task-alpha"
        assert stats["most_failed_tasks"][0]["failure_count"] == 10

    def test_get_stats_mixed_durations(
        self, db_session: Session, sample_tasks: list[Task]
    ) -> None:
        """Test avg_duration_ms calculation with mixed durations."""
        # Create runs with different durations
        runs = [
            Run(
                task_id=sample_tasks[0].id,
                command_snapshot="echo 1",
                status=RunStatus.SUCCESS,
                started_at=datetime.now(UTC),
                duration_ms=1000,
            ),
            Run(
                task_id=sample_tasks[0].id,
                command_snapshot="echo 2",
                status=RunStatus.SUCCESS,
                started_at=datetime.now(UTC),
                duration_ms=2000,
            ),
            Run(
                task_id=sample_tasks[0].id,
                command_snapshot="echo 3",
                status=RunStatus.SUCCESS,
                started_at=datetime.now(UTC),
                duration_ms=3000,
            ),
            # Run without duration (should be excluded from avg)
            Run(
                task_id=sample_tasks[0].id,
                command_snapshot="echo 4",
                status=RunStatus.RUNNING,
                started_at=datetime.now(UTC),
                duration_ms=None,
            ),
        ]
        db_session.add_all(runs)
        db_session.commit()

        stats = get_stats(db_session)

        # Average should be (1000 + 2000 + 3000) / 3 = 2000
        assert stats["avg_duration_ms"] == 2000.0

    def test_get_stats_top_5_most_failed(
        self, db_session: Session, sample_tasks: list[Task]
    ) -> None:
        """Test that most_failed_tasks returns top 5 ordered by failure count."""
        # Create multiple tasks with different failure counts
        extra_tasks = [
            Task(name=f"task-{i}", command=f"echo {i}") for i in range(5, 10)
        ]
        db_session.add_all(extra_tasks)
        db_session.flush()

        all_tasks = sample_tasks + extra_tasks

        # Create failures: task0=10, task1=8, task2=6, task3=4, task4=2, task5=1
        failure_counts = [10, 8, 6, 4, 2, 1, 0, 0, 0]
        for idx, count in enumerate(failure_counts):
            if idx >= len(all_tasks):
                break
            for _ in range(count):
                run = Run(
                    task_id=all_tasks[idx].id,
                    command_snapshot=f"echo fail {idx}",
                    status=RunStatus.FAILED,
                    started_at=datetime.now(UTC),
                    duration_ms=1000,
                )
                db_session.add(run)

        db_session.commit()

        stats = get_stats(db_session)

        # Should return top 5 most failed tasks
        most_failed = stats["most_failed_tasks"]
        assert len(most_failed) == 5

        # Verify ordering by failure count (descending)
        assert most_failed[0]["failure_count"] == 10
        assert most_failed[1]["failure_count"] == 8
        assert most_failed[2]["failure_count"] == 6
        assert most_failed[3]["failure_count"] == 4
        assert most_failed[4]["failure_count"] == 2

        # Verify task names match
        assert most_failed[0]["task_name"] == "task-alpha"
        assert most_failed[1]["task_name"] == "task-beta"
