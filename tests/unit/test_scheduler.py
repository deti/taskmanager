"""Unit tests for task scheduler."""

import time
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from taskmanager.database import Base
from taskmanager.models import Schedule, Task, TriggerType
from taskmanager.scheduler import InvalidTriggerConfigError, TaskScheduler


@pytest.fixture
def db_session(monkeypatch: pytest.MonkeyPatch) -> Session:
    """Create a temporary file-based SQLite session for testing.

    Uses a file-based database to avoid threading issues with APScheduler.
    This ensures the scheduler's background thread can access the same data.
    """
    import tempfile

    # Create temporary database file
    db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")  # noqa: SIM115
    db_url = f"sqlite:///{db_file.name}"

    # Create engine and session
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)
    session = session_local()

    # Set this as the default database URL for the scheduler
    monkeypatch.setenv("DB_URL", db_url)

    try:
        yield session
    finally:
        session.close()
        engine.dispose()

        # Clean up temp file
        import os

        try:  # noqa: SIM105
            os.unlink(db_file.name)  # noqa: PTH108
        except Exception:
            pass


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


@pytest.fixture
def scheduler(db_session: Session) -> TaskScheduler:  # noqa: ARG001
    """Create a fresh scheduler instance for each test.

    Uses the same database as db_session to ensure data consistency.
    """
    # Reset singleton
    import taskmanager.scheduler as scheduler_module

    scheduler_module._scheduler_instance = None  # noqa: SLF001

    # Clear settings cache (DB_URL is already set by db_session fixture)
    from taskmanager.settings import get_settings

    get_settings.cache_clear()

    scheduler = TaskScheduler.get_instance()
    yield scheduler

    # Clean up
    if scheduler._scheduler.running:  # noqa: SLF001
        scheduler.stop(wait=True)

    # Reset singleton again for next test
    scheduler_module._scheduler_instance = None  # noqa: SLF001
    get_settings.cache_clear()


class TestSchedulerLifecycle:
    """Tests for scheduler start/stop lifecycle."""

    def test_scheduler_start_stop(self, scheduler: TaskScheduler) -> None:
        """Verify scheduler starts and stops correctly."""
        # Initially not running
        assert not scheduler._scheduler.running  # noqa: SLF001

        # Start
        scheduler.start()
        assert scheduler._scheduler.running  # noqa: SLF001

        # Stop
        scheduler.stop(wait=True)
        assert not scheduler._scheduler.running  # noqa: SLF001

    def test_scheduler_singleton(self) -> None:
        """Verify TaskScheduler uses singleton pattern."""
        import taskmanager.scheduler as scheduler_module

        scheduler_module._scheduler_instance = None  # noqa: SLF001

        instance1 = TaskScheduler.get_instance()
        instance2 = TaskScheduler.get_instance()

        assert instance1 is instance2

        # Clean up
        scheduler_module._scheduler_instance = None  # noqa: SLF001


class TestAddSchedule:
    """Tests for adding schedules."""

    def test_add_schedule_cron(
        self, scheduler: TaskScheduler, db_session: Session, sample_task: Task
    ) -> None:
        """Add a cron schedule and verify job exists."""
        # Create schedule
        schedule = Schedule(
            task_id=sample_task.id,
            trigger_type=TriggerType.CRON,
            trigger_config='{"cron": "*/5 * * * *"}',
        )
        db_session.add(schedule)
        db_session.commit()

        # Add to scheduler
        scheduler.start()
        scheduler.add_schedule(schedule, db_session)

        # Verify job exists
        job = scheduler._scheduler.get_job(schedule.id)  # noqa: SLF001
        assert job is not None
        assert job.id == schedule.id

        # Verify next_run_at was updated
        db_session.refresh(schedule)
        assert schedule.next_run_at is not None

    def test_add_schedule_interval(
        self, scheduler: TaskScheduler, db_session: Session, sample_task: Task
    ) -> None:
        """Add an interval schedule and verify execution within expected time.

        CRITICAL: This test uses a 1-second interval and verifies execution
        within 3 seconds to ensure the scheduler is working correctly.
        """
        # Create schedule with 1-second interval
        schedule = Schedule(
            task_id=sample_task.id,
            trigger_type=TriggerType.INTERVAL,
            trigger_config='{"interval": {"seconds": 1}}',
        )
        db_session.add(schedule)
        db_session.commit()

        # Mock execute_task to track calls
        with patch("taskmanager.scheduler.execute_task") as mock_execute:
            # Add to scheduler and start
            scheduler.start()
            scheduler.add_schedule(schedule, db_session)

            # Wait up to 3 seconds for execution
            max_wait = 3.0
            start_time = time.time()
            while time.time() - start_time < max_wait:
                if mock_execute.call_count > 0:
                    break
                time.sleep(0.1)

            # Verify execution happened
            assert mock_execute.call_count > 0, (
                f"Task not executed within {max_wait}s. "
                f"Call count: {mock_execute.call_count}"
            )

            # Verify execute_task was called with a Task and Session
            call_args = mock_execute.call_args
            assert call_args is not None
            assert len(call_args[0]) == 2  # (task, db)
            # First arg should be a Task instance
            from taskmanager.models import Task

            assert isinstance(call_args[0][0], Task)

    def test_add_schedule_once(
        self, scheduler: TaskScheduler, db_session: Session, sample_task: Task
    ) -> None:
        """Add a one-time schedule for future datetime."""
        # Create schedule for 10 seconds in the future
        future_time = datetime.now(UTC) + timedelta(seconds=10)
        schedule = Schedule(
            task_id=sample_task.id,
            trigger_type=TriggerType.ONCE,
            trigger_config=f'{{"once": "{future_time.isoformat()}"}}',
        )
        db_session.add(schedule)
        db_session.commit()

        # Add to scheduler
        scheduler.start()
        scheduler.add_schedule(schedule, db_session)

        # Verify job exists and next_run_at is correct
        job = scheduler._scheduler.get_job(schedule.id)  # noqa: SLF001
        assert job is not None

        db_session.refresh(schedule)
        assert schedule.next_run_at is not None
        # Allow 1 second tolerance for scheduling overhead
        # Make schedule.next_run_at timezone-aware if it's naive
        next_run_aware = (
            schedule.next_run_at.replace(tzinfo=UTC)
            if schedule.next_run_at.tzinfo is None
            else schedule.next_run_at
        )
        assert abs((next_run_aware - future_time).total_seconds()) < 1

    def test_add_schedule_invalid_json(
        self, scheduler: TaskScheduler, db_session: Session, sample_task: Task
    ) -> None:
        """Verify InvalidTriggerConfigError on invalid JSON."""
        schedule = Schedule(
            task_id=sample_task.id,
            trigger_type=TriggerType.CRON,
            trigger_config="not valid json",
        )
        db_session.add(schedule)
        db_session.commit()

        with pytest.raises(InvalidTriggerConfigError) as exc_info:
            scheduler.add_schedule(schedule, db_session)

        assert "Invalid JSON" in str(exc_info.value)

    def test_add_schedule_missing_cron_field(
        self, scheduler: TaskScheduler, db_session: Session, sample_task: Task
    ) -> None:
        """Verify InvalidTriggerConfigError when cron field is missing."""
        schedule = Schedule(
            task_id=sample_task.id,
            trigger_type=TriggerType.CRON,
            trigger_config='{"wrong_field": "value"}',
        )
        db_session.add(schedule)
        db_session.commit()

        with pytest.raises(InvalidTriggerConfigError) as exc_info:
            scheduler.add_schedule(schedule, db_session)

        assert "requires 'cron' field" in str(exc_info.value)

    def test_add_schedule_invalid_cron_format(
        self, scheduler: TaskScheduler, db_session: Session, sample_task: Task
    ) -> None:
        """Verify InvalidTriggerConfigError on malformed cron expression."""
        schedule = Schedule(
            task_id=sample_task.id,
            trigger_type=TriggerType.CRON,
            trigger_config='{"cron": "invalid"}',
        )
        db_session.add(schedule)
        db_session.commit()

        with pytest.raises(InvalidTriggerConfigError) as exc_info:
            scheduler.add_schedule(schedule, db_session)

        assert "expected 5 fields" in str(exc_info.value)

    def test_add_schedule_missing_interval_field(
        self, scheduler: TaskScheduler, db_session: Session, sample_task: Task
    ) -> None:
        """Verify InvalidTriggerConfigError when interval field is missing."""
        schedule = Schedule(
            task_id=sample_task.id,
            trigger_type=TriggerType.INTERVAL,
            trigger_config='{"wrong_field": "value"}',
        )
        db_session.add(schedule)
        db_session.commit()

        with pytest.raises(InvalidTriggerConfigError) as exc_info:
            scheduler.add_schedule(schedule, db_session)

        assert "requires 'interval' field" in str(exc_info.value)

    def test_add_schedule_interval_no_time_units(
        self, scheduler: TaskScheduler, db_session: Session, sample_task: Task
    ) -> None:
        """Verify InvalidTriggerConfigError when interval has no valid time units."""
        schedule = Schedule(
            task_id=sample_task.id,
            trigger_type=TriggerType.INTERVAL,
            trigger_config='{"interval": {"invalid_unit": 10}}',
        )
        db_session.add(schedule)
        db_session.commit()

        with pytest.raises(InvalidTriggerConfigError) as exc_info:
            scheduler.add_schedule(schedule, db_session)

        assert "requires at least one time unit" in str(exc_info.value)

    def test_add_schedule_missing_once_field(
        self, scheduler: TaskScheduler, db_session: Session, sample_task: Task
    ) -> None:
        """Verify InvalidTriggerConfigError when once field is missing."""
        schedule = Schedule(
            task_id=sample_task.id,
            trigger_type=TriggerType.ONCE,
            trigger_config='{"wrong_field": "value"}',
        )
        db_session.add(schedule)
        db_session.commit()

        with pytest.raises(InvalidTriggerConfigError) as exc_info:
            scheduler.add_schedule(schedule, db_session)

        assert "requires 'once' field" in str(exc_info.value)

    def test_add_schedule_invalid_once_datetime(
        self, scheduler: TaskScheduler, db_session: Session, sample_task: Task
    ) -> None:
        """Verify InvalidTriggerConfigError on invalid datetime format."""
        schedule = Schedule(
            task_id=sample_task.id,
            trigger_type=TriggerType.ONCE,
            trigger_config='{"once": "not a datetime"}',
        )
        db_session.add(schedule)
        db_session.commit()

        with pytest.raises(InvalidTriggerConfigError) as exc_info:
            scheduler.add_schedule(schedule, db_session)

        assert "Invalid datetime format" in str(exc_info.value)


class TestPauseResumeSchedule:
    """Tests for pausing and resuming schedules."""

    def test_pause_resume_schedule(
        self, scheduler: TaskScheduler, db_session: Session, sample_task: Task
    ) -> None:
        """Verify pause stops execution and resume restarts it."""
        # Create schedule with 1-second interval
        schedule = Schedule(
            task_id=sample_task.id,
            trigger_type=TriggerType.INTERVAL,
            trigger_config='{"interval": {"seconds": 1}}',
        )
        db_session.add(schedule)
        db_session.commit()

        # Mock execute_task
        with patch("taskmanager.scheduler.execute_task") as mock_execute:
            # Add and start
            scheduler.start()
            scheduler.add_schedule(schedule, db_session)

            # Wait for first execution
            max_wait = 3.0
            start_time = time.time()
            while time.time() - start_time < max_wait:
                if mock_execute.call_count > 0:
                    break
                time.sleep(0.1)

            initial_count = mock_execute.call_count
            assert initial_count > 0, "Task should execute before pause"

            # Pause the schedule
            scheduler.pause_schedule(schedule.id, db_session)
            db_session.refresh(schedule)
            assert schedule.enabled is False

            # Reset mock and wait — should not execute
            mock_execute.reset_mock()
            time.sleep(2.0)
            assert (
                mock_execute.call_count == 0
            ), "Task should not execute while paused"

            # Resume the schedule
            scheduler.resume_schedule(schedule.id, db_session)
            db_session.refresh(schedule)
            assert schedule.enabled is True

            # Wait for execution after resume
            start_time = time.time()
            while time.time() - start_time < max_wait:
                if mock_execute.call_count > 0:
                    break
                time.sleep(0.1)

            assert mock_execute.call_count > 0, "Task should execute after resume"


class TestRemoveSchedule:
    """Tests for removing schedules."""

    def test_remove_schedule(
        self, scheduler: TaskScheduler, db_session: Session, sample_task: Task
    ) -> None:
        """Verify job removal from APScheduler."""
        # Create and add schedule
        schedule = Schedule(
            task_id=sample_task.id,
            trigger_type=TriggerType.CRON,
            trigger_config='{"cron": "*/5 * * * *"}',
        )
        db_session.add(schedule)
        db_session.commit()

        scheduler.start()
        scheduler.add_schedule(schedule, db_session)

        # Verify job exists
        assert scheduler._scheduler.get_job(schedule.id) is not None  # noqa: SLF001

        # Remove job
        scheduler.remove_schedule(schedule.id)

        # Verify job is gone
        assert scheduler._scheduler.get_job(schedule.id) is None  # noqa: SLF001

    def test_remove_nonexistent_schedule(self, scheduler: TaskScheduler) -> None:
        """Verify removing nonexistent schedule doesn't raise error."""
        # Should not raise — just log warning
        scheduler.start()
        scheduler.remove_schedule("nonexistent-id")


class TestSchedulerPersistence:
    """Tests for job persistence across scheduler restarts."""

    def test_scheduler_persistence(
        self, monkeypatch: pytest.MonkeyPatch, db_session: Session, sample_task: Task
    ) -> None:
        """Add schedule, stop, restart, verify job reloaded from SQLAlchemyJobStore."""
        # Use a temporary file database for persistence
        import tempfile

        db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")  # noqa: SIM115
        db_url = f"sqlite:///{db_file.name}"

        # Reset singleton
        import taskmanager.scheduler as scheduler_module

        scheduler_module._scheduler_instance = None  # noqa: SLF001

        # Configure database
        monkeypatch.setenv("DB_URL", db_url)

        from taskmanager.settings import get_settings

        get_settings.cache_clear()

        # Create first scheduler instance
        scheduler1 = TaskScheduler.get_instance()
        scheduler1.start()

        # Create schedule
        schedule = Schedule(
            task_id=sample_task.id,
            trigger_type=TriggerType.CRON,
            trigger_config='{"cron": "*/5 * * * *"}',
        )
        db_session.add(schedule)
        db_session.commit()

        # Add schedule to first instance
        scheduler1.add_schedule(schedule, db_session)

        # Verify job exists
        assert scheduler1._scheduler.get_job(schedule.id) is not None  # noqa: SLF001

        # Stop first scheduler
        scheduler1.stop(wait=True)

        # Reset singleton and create new instance
        scheduler_module._scheduler_instance = None  # noqa: SLF001
        get_settings.cache_clear()

        scheduler2 = TaskScheduler.get_instance()
        scheduler2.start()

        # Verify job was reloaded from job store
        job = scheduler2._scheduler.get_job(schedule.id)  # noqa: SLF001
        assert job is not None, "Job should be reloaded from SQLAlchemyJobStore"
        assert job.id == schedule.id

        # Clean up
        scheduler2.stop(wait=True)
        scheduler_module._scheduler_instance = None  # noqa: SLF001
        get_settings.cache_clear()

        import os

        os.unlink(db_file.name)  # noqa: PTH108


class TestGetNextRunTime:
    """Tests for get_next_run_time method."""

    def test_get_next_run_time(
        self, scheduler: TaskScheduler, db_session: Session, sample_task: Task
    ) -> None:
        """Verify get_next_run_time returns correct value."""
        schedule = Schedule(
            task_id=sample_task.id,
            trigger_type=TriggerType.CRON,
            trigger_config='{"cron": "*/5 * * * *"}',
        )
        db_session.add(schedule)
        db_session.commit()

        scheduler.start()
        scheduler.add_schedule(schedule, db_session)

        # Get next run time
        next_run = scheduler.get_next_run_time(schedule.id)
        assert next_run is not None
        assert isinstance(next_run, datetime)

    def test_get_next_run_time_nonexistent(self, scheduler: TaskScheduler) -> None:
        """Verify get_next_run_time returns None for nonexistent job."""
        scheduler.start()
        assert scheduler.get_next_run_time("nonexistent-id") is None
