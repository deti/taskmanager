"""Unit tests for schedule service layer."""

import json
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from taskmanager.database import Base
from taskmanager.exceptions import (
    DuplicateScheduleError,
    ScheduleNotFoundError,
    ScheduleValidationError,
    TaskNotFoundError,
)
from taskmanager.models import Task, TriggerType
from taskmanager.services import schedule_service


@pytest.fixture
def db_session() -> Session:
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)
    session = session_local()
    yield session
    session.close()


@pytest.fixture
def sample_task(db_session: Session) -> Task:
    """Create a sample task for testing."""
    task = Task(
        name="test_task",
        command="echo 'test'",
        description="Test task",
    )
    db_session.add(task)
    db_session.flush()
    return task


def test_create_schedule_cron(db_session: Session, sample_task: Task) -> None:
    """Test creating a CRON schedule."""
    trigger_config = {"cron": "0 0 * * *"}

    schedule = schedule_service.create_schedule(
        session=db_session,
        task_id=sample_task.id,
        trigger_type=TriggerType.CRON,
        trigger_config=trigger_config,
    )

    assert schedule.id is not None
    assert schedule.task_id == sample_task.id
    assert schedule.trigger_type == TriggerType.CRON
    assert json.loads(schedule.trigger_config) == trigger_config
    assert schedule.enabled is True
    assert schedule.created_at is not None


def test_create_schedule_interval(db_session: Session, sample_task: Task) -> None:
    """Test creating an INTERVAL schedule."""
    trigger_config = {"interval": {"minutes": 30, "seconds": 15}}

    schedule = schedule_service.create_schedule(
        session=db_session,
        task_id=sample_task.id,
        trigger_type=TriggerType.INTERVAL,
        trigger_config=trigger_config,
    )

    assert schedule.id is not None
    assert schedule.task_id == sample_task.id
    assert schedule.trigger_type == TriggerType.INTERVAL
    assert json.loads(schedule.trigger_config) == trigger_config
    assert schedule.enabled is True


def test_create_schedule_once(db_session: Session, sample_task: Task) -> None:
    """Test creating a ONCE schedule."""
    trigger_config = {"once": "2026-12-31T23:59:59Z"}

    schedule = schedule_service.create_schedule(
        session=db_session,
        task_id=sample_task.id,
        trigger_type=TriggerType.ONCE,
        trigger_config=trigger_config,
    )

    assert schedule.id is not None
    assert schedule.task_id == sample_task.id
    assert schedule.trigger_type == TriggerType.ONCE
    assert json.loads(schedule.trigger_config) == trigger_config
    assert schedule.enabled is True


def test_create_schedule_disabled(db_session: Session, sample_task: Task) -> None:
    """Test creating a disabled schedule."""
    trigger_config = {"cron": "0 0 * * *"}

    schedule = schedule_service.create_schedule(
        session=db_session,
        task_id=sample_task.id,
        trigger_type=TriggerType.CRON,
        trigger_config=trigger_config,
        enabled=False,
    )

    assert schedule.enabled is False


def test_create_schedule_task_not_found(db_session: Session) -> None:
    """Test creating a schedule with non-existent task."""
    fake_task_id = str(uuid.uuid4())
    trigger_config = {"cron": "0 0 * * *"}

    with pytest.raises(TaskNotFoundError) as exc_info:
        schedule_service.create_schedule(
            session=db_session,
            task_id=fake_task_id,
            trigger_type=TriggerType.CRON,
            trigger_config=trigger_config,
        )

    assert fake_task_id in str(exc_info.value)


def test_create_schedule_duplicate(db_session: Session, sample_task: Task) -> None:
    """Test creating a duplicate schedule (same task_id + trigger_type)."""
    trigger_config = {"cron": "0 0 * * *"}

    # Create first schedule
    schedule_service.create_schedule(
        session=db_session,
        task_id=sample_task.id,
        trigger_type=TriggerType.CRON,
        trigger_config=trigger_config,
    )

    # Attempt to create duplicate
    with pytest.raises(DuplicateScheduleError) as exc_info:
        schedule_service.create_schedule(
            session=db_session,
            task_id=sample_task.id,
            trigger_type=TriggerType.CRON,
            trigger_config={"cron": "0 12 * * *"},  # Different config, same type
        )

    assert sample_task.id in str(exc_info.value)
    assert "cron" in str(exc_info.value).lower()


def test_create_schedule_different_trigger_types(
    db_session: Session, sample_task: Task
) -> None:
    """Test creating multiple schedules with different trigger types for the same task."""
    # Create CRON schedule
    schedule_service.create_schedule(
        session=db_session,
        task_id=sample_task.id,
        trigger_type=TriggerType.CRON,
        trigger_config={"cron": "0 0 * * *"},
    )

    # Create INTERVAL schedule (should succeed - different trigger type)
    schedule = schedule_service.create_schedule(
        session=db_session,
        task_id=sample_task.id,
        trigger_type=TriggerType.INTERVAL,
        trigger_config={"interval": {"hours": 1}},
    )

    assert schedule.trigger_type == TriggerType.INTERVAL


def test_create_schedule_invalid_cron_missing_field(
    db_session: Session, sample_task: Task
) -> None:
    """Test creating CRON schedule with missing 'cron' field."""
    trigger_config = {"invalid": "0 0 * * *"}

    with pytest.raises(ScheduleValidationError) as exc_info:
        schedule_service.create_schedule(
            session=db_session,
            task_id=sample_task.id,
            trigger_type=TriggerType.CRON,
            trigger_config=trigger_config,
        )

    assert "cron" in str(exc_info.value).lower()


def test_create_schedule_invalid_cron_not_string(
    db_session: Session, sample_task: Task
) -> None:
    """Test creating CRON schedule with non-string cron expression."""
    trigger_config = {"cron": 12345}

    with pytest.raises(ScheduleValidationError) as exc_info:
        schedule_service.create_schedule(
            session=db_session,
            task_id=sample_task.id,
            trigger_type=TriggerType.CRON,
            trigger_config=trigger_config,
        )

    assert "string" in str(exc_info.value).lower()


def test_create_schedule_invalid_cron_expression(
    db_session: Session, sample_task: Task
) -> None:
    """Test creating CRON schedule with invalid cron expression format."""
    trigger_config = {"cron": "invalid cron"}

    with pytest.raises(ScheduleValidationError) as exc_info:
        schedule_service.create_schedule(
            session=db_session,
            task_id=sample_task.id,
            trigger_type=TriggerType.CRON,
            trigger_config=trigger_config,
        )

    assert "invalid cron" in str(exc_info.value).lower()


def test_create_schedule_invalid_interval_missing_field(
    db_session: Session, sample_task: Task
) -> None:
    """Test creating INTERVAL schedule with missing 'interval' field."""
    trigger_config = {"invalid": {"minutes": 30}}

    with pytest.raises(ScheduleValidationError) as exc_info:
        schedule_service.create_schedule(
            session=db_session,
            task_id=sample_task.id,
            trigger_type=TriggerType.INTERVAL,
            trigger_config=trigger_config,
        )

    assert "interval" in str(exc_info.value).lower()


def test_create_schedule_invalid_interval_not_dict(
    db_session: Session, sample_task: Task
) -> None:
    """Test creating INTERVAL schedule with non-dict interval field."""
    trigger_config = {"interval": "30 minutes"}

    with pytest.raises(ScheduleValidationError) as exc_info:
        schedule_service.create_schedule(
            session=db_session,
            task_id=sample_task.id,
            trigger_type=TriggerType.INTERVAL,
            trigger_config=trigger_config,
        )

    assert "dictionary" in str(exc_info.value).lower()


def test_create_schedule_invalid_interval_no_time_units(
    db_session: Session, sample_task: Task
) -> None:
    """Test creating INTERVAL schedule with no valid time units."""
    trigger_config = {"interval": {"invalid_unit": 30}}

    with pytest.raises(ScheduleValidationError) as exc_info:
        schedule_service.create_schedule(
            session=db_session,
            task_id=sample_task.id,
            trigger_type=TriggerType.INTERVAL,
            trigger_config=trigger_config,
        )

    assert "at least one" in str(exc_info.value).lower()


def test_create_schedule_invalid_interval_negative_value(
    db_session: Session, sample_task: Task
) -> None:
    """Test creating INTERVAL schedule with negative time value."""
    trigger_config = {"interval": {"minutes": -30}}

    with pytest.raises(ScheduleValidationError) as exc_info:
        schedule_service.create_schedule(
            session=db_session,
            task_id=sample_task.id,
            trigger_type=TriggerType.INTERVAL,
            trigger_config=trigger_config,
        )

    assert "positive integer" in str(exc_info.value).lower()


def test_create_schedule_invalid_once_missing_field(
    db_session: Session, sample_task: Task
) -> None:
    """Test creating ONCE schedule with missing 'once' field."""
    trigger_config = {"invalid": "2026-12-31T23:59:59Z"}

    with pytest.raises(ScheduleValidationError) as exc_info:
        schedule_service.create_schedule(
            session=db_session,
            task_id=sample_task.id,
            trigger_type=TriggerType.ONCE,
            trigger_config=trigger_config,
        )

    assert "once" in str(exc_info.value).lower()


def test_create_schedule_invalid_once_not_string(
    db_session: Session, sample_task: Task
) -> None:
    """Test creating ONCE schedule with non-string datetime."""
    trigger_config = {"once": 1234567890}

    with pytest.raises(ScheduleValidationError) as exc_info:
        schedule_service.create_schedule(
            session=db_session,
            task_id=sample_task.id,
            trigger_type=TriggerType.ONCE,
            trigger_config=trigger_config,
        )

    assert "string" in str(exc_info.value).lower()


def test_create_schedule_invalid_once_datetime(
    db_session: Session, sample_task: Task
) -> None:
    """Test creating ONCE schedule with invalid ISO-8601 datetime."""
    trigger_config = {"once": "not-a-datetime"}

    with pytest.raises(ScheduleValidationError) as exc_info:
        schedule_service.create_schedule(
            session=db_session,
            task_id=sample_task.id,
            trigger_type=TriggerType.ONCE,
            trigger_config=trigger_config,
        )

    assert "iso-8601" in str(exc_info.value).lower()


def test_get_schedule(db_session: Session, sample_task: Task) -> None:
    """Test retrieving a schedule by ID."""
    created = schedule_service.create_schedule(
        session=db_session,
        task_id=sample_task.id,
        trigger_type=TriggerType.CRON,
        trigger_config={"cron": "0 0 * * *"},
    )

    schedule = schedule_service.get_schedule(db_session, created.id)

    assert schedule.id == created.id
    assert schedule.task_id == sample_task.id
    assert schedule.trigger_type == TriggerType.CRON


def test_get_schedule_not_found(db_session: Session) -> None:
    """Test retrieving a non-existent schedule."""
    fake_id = str(uuid.uuid4())

    with pytest.raises(ScheduleNotFoundError) as exc_info:
        schedule_service.get_schedule(db_session, fake_id)

    assert fake_id in str(exc_info.value)


def test_list_schedules_all(db_session: Session, sample_task: Task) -> None:
    """Test listing all schedules."""
    # Create multiple schedules
    schedule_service.create_schedule(
        session=db_session,
        task_id=sample_task.id,
        trigger_type=TriggerType.CRON,
        trigger_config={"cron": "0 0 * * *"},
    )
    schedule_service.create_schedule(
        session=db_session,
        task_id=sample_task.id,
        trigger_type=TriggerType.INTERVAL,
        trigger_config={"interval": {"hours": 1}},
    )

    schedules = schedule_service.list_schedules(db_session)

    assert len(schedules) == 2


def test_list_schedules_by_task_id(db_session: Session) -> None:
    """Test listing schedules filtered by task_id."""
    # Create two tasks
    task1 = Task(name="task1", command="echo '1'")
    task2 = Task(name="task2", command="echo '2'")
    db_session.add_all([task1, task2])
    db_session.flush()

    # Create schedules for each task
    schedule_service.create_schedule(
        session=db_session,
        task_id=task1.id,
        trigger_type=TriggerType.CRON,
        trigger_config={"cron": "0 0 * * *"},
    )
    schedule_service.create_schedule(
        session=db_session,
        task_id=task2.id,
        trigger_type=TriggerType.CRON,
        trigger_config={"cron": "0 12 * * *"},
    )

    # List schedules for task1
    schedules = schedule_service.list_schedules(db_session, task_id=task1.id)

    assert len(schedules) == 1
    assert schedules[0].task_id == task1.id


def test_list_schedules_by_enabled(db_session: Session, sample_task: Task) -> None:
    """Test listing schedules filtered by enabled status."""
    # Create enabled and disabled schedules
    schedule_service.create_schedule(
        session=db_session,
        task_id=sample_task.id,
        trigger_type=TriggerType.CRON,
        trigger_config={"cron": "0 0 * * *"},
        enabled=True,
    )
    schedule_service.create_schedule(
        session=db_session,
        task_id=sample_task.id,
        trigger_type=TriggerType.INTERVAL,
        trigger_config={"interval": {"hours": 1}},
        enabled=False,
    )

    # List enabled schedules
    enabled_schedules = schedule_service.list_schedules(db_session, enabled=True)
    assert len(enabled_schedules) == 1
    assert enabled_schedules[0].enabled is True

    # List disabled schedules
    disabled_schedules = schedule_service.list_schedules(db_session, enabled=False)
    assert len(disabled_schedules) == 1
    assert disabled_schedules[0].enabled is False


def test_list_schedules_empty(db_session: Session) -> None:
    """Test listing schedules when none exist."""
    schedules = schedule_service.list_schedules(db_session)
    assert schedules == []


def test_update_schedule_trigger_config(
    db_session: Session, sample_task: Task
) -> None:
    """Test updating schedule trigger configuration."""
    schedule = schedule_service.create_schedule(
        session=db_session,
        task_id=sample_task.id,
        trigger_type=TriggerType.CRON,
        trigger_config={"cron": "0 0 * * *"},
    )

    new_config = {"cron": "0 12 * * *"}
    updated = schedule_service.update_schedule(
        session=db_session,
        schedule_id=schedule.id,
        trigger_config=new_config,
    )

    assert json.loads(updated.trigger_config) == new_config
    assert updated.id == schedule.id


def test_update_schedule_enabled(db_session: Session, sample_task: Task) -> None:
    """Test updating schedule enabled status."""
    schedule = schedule_service.create_schedule(
        session=db_session,
        task_id=sample_task.id,
        trigger_type=TriggerType.CRON,
        trigger_config={"cron": "0 0 * * *"},
        enabled=True,
    )

    # Disable schedule
    updated = schedule_service.update_schedule(
        session=db_session,
        schedule_id=schedule.id,
        enabled=False,
    )

    assert updated.enabled is False
    assert updated.id == schedule.id


def test_update_schedule_both_fields(db_session: Session, sample_task: Task) -> None:
    """Test updating both trigger_config and enabled status."""
    schedule = schedule_service.create_schedule(
        session=db_session,
        task_id=sample_task.id,
        trigger_type=TriggerType.CRON,
        trigger_config={"cron": "0 0 * * *"},
        enabled=True,
    )

    new_config = {"cron": "0 12 * * *"}
    updated = schedule_service.update_schedule(
        session=db_session,
        schedule_id=schedule.id,
        trigger_config=new_config,
        enabled=False,
    )

    assert json.loads(updated.trigger_config) == new_config
    assert updated.enabled is False


def test_update_schedule_not_found(db_session: Session) -> None:
    """Test updating a non-existent schedule."""
    fake_id = str(uuid.uuid4())

    with pytest.raises(ScheduleNotFoundError):
        schedule_service.update_schedule(
            session=db_session,
            schedule_id=fake_id,
            enabled=False,
        )


def test_update_schedule_invalid_trigger_config(
    db_session: Session, sample_task: Task
) -> None:
    """Test updating schedule with invalid trigger configuration."""
    schedule = schedule_service.create_schedule(
        session=db_session,
        task_id=sample_task.id,
        trigger_type=TriggerType.CRON,
        trigger_config={"cron": "0 0 * * *"},
    )

    # Attempt to update with invalid config
    with pytest.raises(ScheduleValidationError):
        schedule_service.update_schedule(
            session=db_session,
            schedule_id=schedule.id,
            trigger_config={"invalid": "field"},
        )


def test_delete_schedule(db_session: Session, sample_task: Task) -> None:
    """Test deleting a schedule."""
    schedule = schedule_service.create_schedule(
        session=db_session,
        task_id=sample_task.id,
        trigger_type=TriggerType.CRON,
        trigger_config={"cron": "0 0 * * *"},
    )

    deleted = schedule_service.delete_schedule(db_session, schedule.id)

    assert deleted.id == schedule.id

    # Verify schedule is deleted
    with pytest.raises(ScheduleNotFoundError):
        schedule_service.get_schedule(db_session, schedule.id)


def test_delete_schedule_not_found(db_session: Session) -> None:
    """Test deleting a non-existent schedule."""
    fake_id = str(uuid.uuid4())

    with pytest.raises(ScheduleNotFoundError):
        schedule_service.delete_schedule(db_session, fake_id)
