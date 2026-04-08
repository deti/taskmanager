"""Unit tests for run service layer.

Tests all read operations using in-memory SQLite database.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from taskmanager.database import Base
from taskmanager.exceptions import RunNotFoundError
from taskmanager.models import Run, RunStatus, Task
from taskmanager.services import get_run, get_runs_for_task, list_runs


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
def sample_task(db_session: Session) -> Task:
    """Create a sample task for testing."""
    task = Task(
        name="test-task",
        command="echo test",
        description="Test task",
    )
    db_session.add(task)
    db_session.flush()
    return task


@pytest.fixture
def sample_run(db_session: Session, sample_task: Task) -> Run:
    """Create a sample run for testing."""
    run = Run(
        task_id=sample_task.id,
        command_snapshot="echo test",
        status=RunStatus.SUCCESS,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        exit_code=0,
    )
    db_session.add(run)
    db_session.flush()
    return run


class TestListRuns:
    """Tests for list_runs function."""

    def test_list_runs_empty(self, db_session: Session) -> None:
        """Test listing runs when none exist."""
        runs = list_runs(db_session)
        assert runs == []

    def test_list_runs_all(
        self, db_session: Session, sample_task: Task
    ) -> None:
        """Test listing all runs without filters."""
        # Create multiple runs
        run1 = Run(
            task_id=sample_task.id,
            command_snapshot="echo 1",
            status=RunStatus.SUCCESS,
            started_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
        run2 = Run(
            task_id=sample_task.id,
            command_snapshot="echo 2",
            status=RunStatus.FAILED,
            started_at=datetime(2026, 4, 2, tzinfo=UTC),
        )
        run3 = Run(
            task_id=sample_task.id,
            command_snapshot="echo 3",
            status=RunStatus.RUNNING,
            started_at=datetime(2026, 4, 3, tzinfo=UTC),
        )
        db_session.add_all([run1, run2, run3])
        db_session.commit()

        runs = list_runs(db_session)
        assert len(runs) == 3

    def test_list_runs_filter_by_task_id(
        self, db_session: Session
    ) -> None:
        """Test filtering runs by task_id."""
        # Create two tasks
        task1 = Task(name="task1", command="echo 1")
        task2 = Task(name="task2", command="echo 2")
        db_session.add_all([task1, task2])
        db_session.flush()

        # Create runs for each task
        run1 = Run(
            task_id=task1.id,
            command_snapshot="echo 1",
            status=RunStatus.SUCCESS,
            started_at=datetime.now(UTC),
        )
        run2 = Run(
            task_id=task2.id,
            command_snapshot="echo 2",
            status=RunStatus.SUCCESS,
            started_at=datetime.now(UTC),
        )
        run3 = Run(
            task_id=task1.id,
            command_snapshot="echo 1 again",
            status=RunStatus.FAILED,
            started_at=datetime.now(UTC),
        )
        db_session.add_all([run1, run2, run3])
        db_session.commit()

        # Filter by task1 ID
        runs = list_runs(db_session, task_id=task1.id)
        assert len(runs) == 2
        assert all(r.task_id == task1.id for r in runs)

        # Filter by task2 ID
        runs = list_runs(db_session, task_id=task2.id)
        assert len(runs) == 1
        assert runs[0].task_id == task2.id

    def test_list_runs_filter_by_status(
        self, db_session: Session, sample_task: Task
    ) -> None:
        """Test filtering runs by status."""
        run1 = Run(
            task_id=sample_task.id,
            command_snapshot="echo 1",
            status=RunStatus.SUCCESS,
            started_at=datetime.now(UTC),
        )
        run2 = Run(
            task_id=sample_task.id,
            command_snapshot="echo 2",
            status=RunStatus.FAILED,
            started_at=datetime.now(UTC),
        )
        run3 = Run(
            task_id=sample_task.id,
            command_snapshot="echo 3",
            status=RunStatus.SUCCESS,
            started_at=datetime.now(UTC),
        )
        db_session.add_all([run1, run2, run3])
        db_session.commit()

        # Filter by SUCCESS status
        runs = list_runs(db_session, status=RunStatus.SUCCESS)
        assert len(runs) == 2
        assert all(r.status == RunStatus.SUCCESS for r in runs)

        # Filter by FAILED status
        runs = list_runs(db_session, status=RunStatus.FAILED)
        assert len(runs) == 1
        assert runs[0].status == RunStatus.FAILED

    def test_list_runs_with_limit(
        self, db_session: Session, sample_task: Task
    ) -> None:
        """Test limiting the number of runs returned."""
        # Create 5 runs
        for i in range(5):
            run = Run(
                task_id=sample_task.id,
                command_snapshot=f"echo {i}",
                status=RunStatus.SUCCESS,
                started_at=datetime(2026, 4, i + 1, tzinfo=UTC),
            )
            db_session.add(run)
        db_session.commit()

        # Request only 3 runs
        runs = list_runs(db_session, limit=3)
        assert len(runs) == 3

    def test_list_runs_ordering(
        self, db_session: Session, sample_task: Task
    ) -> None:
        """Test that runs are ordered by started_at DESC (most recent first)."""
        run1 = Run(
            task_id=sample_task.id,
            command_snapshot="echo 1",
            status=RunStatus.SUCCESS,
            started_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
        run2 = Run(
            task_id=sample_task.id,
            command_snapshot="echo 2",
            status=RunStatus.SUCCESS,
            started_at=datetime(2026, 4, 3, tzinfo=UTC),
        )
        run3 = Run(
            task_id=sample_task.id,
            command_snapshot="echo 3",
            status=RunStatus.SUCCESS,
            started_at=datetime(2026, 4, 2, tzinfo=UTC),
        )
        db_session.add_all([run1, run2, run3])
        db_session.commit()

        runs = list_runs(db_session)
        assert len(runs) == 3
        # Most recent first (run2 -> run3 -> run1)
        # SQLite strips timezone info, so compare without timezone
        assert runs[0].started_at == datetime(2026, 4, 3)
        assert runs[1].started_at == datetime(2026, 4, 2)
        assert runs[2].started_at == datetime(2026, 4, 1)

    def test_list_runs_combined_filters(
        self, db_session: Session
    ) -> None:
        """Test combining multiple filters."""
        task1 = Task(name="task1", command="echo 1")
        task2 = Task(name="task2", command="echo 2")
        db_session.add_all([task1, task2])
        db_session.flush()

        # Create runs with different task_id and status combinations
        run1 = Run(
            task_id=task1.id,
            command_snapshot="echo 1",
            status=RunStatus.SUCCESS,
            started_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
        run2 = Run(
            task_id=task1.id,
            command_snapshot="echo 1",
            status=RunStatus.FAILED,
            started_at=datetime(2026, 4, 2, tzinfo=UTC),
        )
        run3 = Run(
            task_id=task2.id,
            command_snapshot="echo 2",
            status=RunStatus.SUCCESS,
            started_at=datetime(2026, 4, 3, tzinfo=UTC),
        )
        db_session.add_all([run1, run2, run3])
        db_session.commit()

        # Filter by task1 and SUCCESS status
        runs = list_runs(
            db_session, task_id=task1.id, status=RunStatus.SUCCESS
        )
        assert len(runs) == 1
        assert runs[0].task_id == task1.id
        assert runs[0].status == RunStatus.SUCCESS


class TestGetRun:
    """Tests for get_run function."""

    def test_get_run_exists(
        self, db_session: Session, sample_run: Run
    ) -> None:
        """Test retrieving an existing run by ID."""
        db_session.commit()

        retrieved = get_run(db_session, sample_run.id)

        assert retrieved.id == sample_run.id
        assert retrieved.task_id == sample_run.task_id
        assert retrieved.status == sample_run.status

    def test_get_run_not_found(self, db_session: Session) -> None:
        """Test that retrieving non-existent run raises error."""
        fake_id = "00000000-0000-0000-0000-000000000000"

        with pytest.raises(RunNotFoundError) as exc_info:
            get_run(db_session, fake_id)

        assert exc_info.value.run_id == fake_id
        assert "not found" in str(exc_info.value)


class TestGetRunsForTask:
    """Tests for get_runs_for_task function."""

    def test_get_runs_for_task_success(
        self, db_session: Session, sample_task: Task
    ) -> None:
        """Test retrieving runs for a task by task name."""
        # Create multiple runs for the task
        run1 = Run(
            task_id=sample_task.id,
            command_snapshot="echo 1",
            status=RunStatus.SUCCESS,
            started_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
        run2 = Run(
            task_id=sample_task.id,
            command_snapshot="echo 2",
            status=RunStatus.FAILED,
            started_at=datetime(2026, 4, 2, tzinfo=UTC),
        )
        db_session.add_all([run1, run2])
        db_session.commit()

        runs = get_runs_for_task(db_session, "test-task")

        assert len(runs) == 2
        assert all(r.task_id == sample_task.id for r in runs)

    def test_get_runs_for_task_no_runs(
        self, db_session: Session, sample_task: Task
    ) -> None:
        """Test retrieving runs for a task with no runs returns empty list."""
        db_session.commit()

        runs = get_runs_for_task(db_session, "test-task")
        assert runs == []

    def test_get_runs_for_task_ordering(
        self, db_session: Session, sample_task: Task
    ) -> None:
        """Test that runs are ordered by started_at DESC (most recent first)."""
        run1 = Run(
            task_id=sample_task.id,
            command_snapshot="echo 1",
            status=RunStatus.SUCCESS,
            started_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
        run2 = Run(
            task_id=sample_task.id,
            command_snapshot="echo 2",
            status=RunStatus.SUCCESS,
            started_at=datetime(2026, 4, 3, tzinfo=UTC),
        )
        run3 = Run(
            task_id=sample_task.id,
            command_snapshot="echo 3",
            status=RunStatus.SUCCESS,
            started_at=datetime(2026, 4, 2, tzinfo=UTC),
        )
        db_session.add_all([run1, run2, run3])
        db_session.commit()

        runs = get_runs_for_task(db_session, "test-task")
        assert len(runs) == 3
        # Most recent first (run2 -> run3 -> run1)
        # SQLite strips timezone info, so compare without timezone
        assert runs[0].started_at == datetime(2026, 4, 3)
        assert runs[1].started_at == datetime(2026, 4, 2)
        assert runs[2].started_at == datetime(2026, 4, 1)

    def test_get_runs_for_task_multiple_tasks(
        self, db_session: Session
    ) -> None:
        """Test that get_runs_for_task only returns runs for the specified task."""
        task1 = Task(name="task1", command="echo 1")
        task2 = Task(name="task2", command="echo 2")
        db_session.add_all([task1, task2])
        db_session.flush()

        # Create runs for both tasks
        run1 = Run(
            task_id=task1.id,
            command_snapshot="echo 1",
            status=RunStatus.SUCCESS,
            started_at=datetime.now(UTC),
        )
        run2 = Run(
            task_id=task2.id,
            command_snapshot="echo 2",
            status=RunStatus.SUCCESS,
            started_at=datetime.now(UTC),
        )
        run3 = Run(
            task_id=task1.id,
            command_snapshot="echo 1 again",
            status=RunStatus.FAILED,
            started_at=datetime.now(UTC),
        )
        db_session.add_all([run1, run2, run3])
        db_session.commit()

        # Get runs for task1
        runs = get_runs_for_task(db_session, "task1")
        assert len(runs) == 2
        assert all(r.task_id == task1.id for r in runs)

        # Get runs for task2
        runs = get_runs_for_task(db_session, "task2")
        assert len(runs) == 1
        assert runs[0].task_id == task2.id
