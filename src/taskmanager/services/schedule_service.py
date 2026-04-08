"""Schedule service layer — business logic for schedule operations.

This module provides CRUD operations for schedules, decoupled from
CLI and API frameworks. All functions use session dependency injection.

Schedules define when and how often tasks should be executed automatically.
Each schedule has a trigger type (cron, interval, or once) with corresponding
configuration stored as JSON.
"""

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from taskmanager.exceptions import (
    DuplicateScheduleError,
    ScheduleNotFoundError,
    ScheduleValidationError,
    TaskNotFoundError,
)
from taskmanager.models import Schedule, Task, TriggerType


def _validate_cron_config(trigger_config: dict[str, Any]) -> None:
    """Validate CRON trigger configuration."""
    if "cron" not in trigger_config:
        msg = "CRON trigger requires 'cron' field with cron expression"
        raise ScheduleValidationError(msg)
    if not isinstance(trigger_config["cron"], str):
        msg = "CRON expression must be a string"
        raise ScheduleValidationError(msg)
    # Basic validation: cron expression should have 5-6 fields
    fields = trigger_config["cron"].split()
    if len(fields) < 5 or len(fields) > 6:
        msg = f"Invalid cron expression: '{trigger_config['cron']}' (expected 5-6 fields)"
        raise ScheduleValidationError(msg)


def _validate_interval_config(trigger_config: dict[str, Any]) -> None:
    """Validate INTERVAL trigger configuration."""
    if "interval" not in trigger_config:
        msg = "INTERVAL trigger requires 'interval' field"
        raise ScheduleValidationError(msg)
    interval = trigger_config["interval"]
    if not isinstance(interval, dict):
        msg = "INTERVAL field must be a dictionary"
        raise ScheduleValidationError(msg)
    # Validate that at least one time unit is specified
    valid_units = {"weeks", "days", "hours", "minutes", "seconds"}
    provided_units = set(interval.keys())
    if not provided_units.intersection(valid_units):
        msg = f"INTERVAL must contain at least one of: {', '.join(valid_units)}"
        raise ScheduleValidationError(msg)
    # Validate that all values are positive integers
    for unit, value in interval.items():
        if unit not in valid_units:
            msg = f"Unknown interval unit: '{unit}'"
            raise ScheduleValidationError(msg)
        if not isinstance(value, int) or value <= 0:
            msg = f"INTERVAL {unit} must be a positive integer, got {value}"
            raise ScheduleValidationError(msg)


def _validate_once_config(trigger_config: dict[str, Any]) -> None:
    """Validate ONCE trigger configuration."""
    if "once" not in trigger_config:
        msg = "ONCE trigger requires 'once' field with ISO-8601 datetime"
        raise ScheduleValidationError(msg)
    if not isinstance(trigger_config["once"], str):
        msg = "ONCE datetime must be a string"
        raise ScheduleValidationError(msg)
    # Validate ISO-8601 format
    try:
        datetime.fromisoformat(trigger_config["once"].replace("Z", "+00:00"))
    except ValueError as e:
        msg = f"Invalid ISO-8601 datetime: '{trigger_config['once']}' ({e})"
        raise ScheduleValidationError(msg) from e


def _validate_trigger_config(
    trigger_type: TriggerType, trigger_config: dict[str, Any]
) -> None:
    """Validate trigger configuration JSON structure.

    Parameters
    ----------
    trigger_type:
        The type of trigger (CRON, INTERVAL, ONCE).
    trigger_config:
        The configuration dictionary to validate.

    Raises
    ------
    ScheduleValidationError
        If the configuration is invalid for the given trigger type.
    """
    if trigger_type == TriggerType.CRON:
        _validate_cron_config(trigger_config)
    elif trigger_type == TriggerType.INTERVAL:
        _validate_interval_config(trigger_config)
    elif trigger_type == TriggerType.ONCE:
        _validate_once_config(trigger_config)


def create_schedule(
    session: Session,
    task_id: str,
    trigger_type: TriggerType,
    trigger_config: dict[str, Any],
    enabled: bool = True,
) -> Schedule:
    """Create and persist a new schedule.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    task_id:
        UUID of the task to schedule.
    trigger_type:
        Type of trigger (CRON, INTERVAL, ONCE).
    trigger_config:
        Configuration dictionary for the trigger type.
    enabled:
        Whether the schedule is enabled (default: True).

    Returns
    -------
    Schedule
        The created Schedule object.

    Raises
    ------
    TaskNotFoundError
        If the task with the given ID does not exist.
    DuplicateScheduleError
        If a schedule with the same task_id and trigger_type already exists.
    ScheduleValidationError
        If the trigger configuration is invalid.
    """
    # Validate task exists
    stmt = select(Task).where(Task.id == task_id)
    result = session.execute(stmt)
    task = result.scalar_one_or_none()
    if task is None:
        raise TaskNotFoundError(task_id)

    # Validate trigger configuration
    _validate_trigger_config(trigger_type, trigger_config)

    # Check for duplicate schedule (task_id + trigger_type must be unique)
    existing_stmt = select(Schedule).where(
        Schedule.task_id == task_id, Schedule.trigger_type == trigger_type
    )
    existing = session.execute(existing_stmt).scalar_one_or_none()
    if existing is not None:
        raise DuplicateScheduleError(task_id, trigger_type)

    # Create schedule
    schedule = Schedule(
        task_id=task_id,
        trigger_type=trigger_type,
        trigger_config=json.dumps(trigger_config),
        enabled=enabled,
    )
    session.add(schedule)
    session.flush()

    # TODO(W3T3.2): Register job with APScheduler after TaskScheduler is implemented

    return schedule


def get_schedule(session: Session, schedule_id: str) -> Schedule:
    """Retrieve schedule by ID.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    schedule_id:
        The UUID of the schedule to retrieve.

    Returns
    -------
    Schedule
        The retrieved Schedule object.

    Raises
    ------
    ScheduleNotFoundError
        If no schedule with the given ID exists.
    """
    stmt = select(Schedule).where(Schedule.id == schedule_id)
    result = session.execute(stmt)
    schedule = result.scalar_one_or_none()

    if schedule is None:
        raise ScheduleNotFoundError(schedule_id)

    return schedule


def list_schedules(
    session: Session,
    task_id: str | None = None,
    enabled: bool | None = None,
) -> list[Schedule]:
    """List all schedules with optional filtering.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    task_id:
        Optional task ID to filter schedules by.
    enabled:
        Optional enabled status to filter by.

    Returns
    -------
    list[Schedule]
        List of Schedule objects matching the filter criteria.
        Returns empty list if no matches.
    """
    stmt = select(Schedule)

    if task_id is not None:
        stmt = stmt.where(Schedule.task_id == task_id)

    if enabled is not None:
        stmt = stmt.where(Schedule.enabled == enabled)

    result = session.execute(stmt)
    return list(result.scalars().all())


def update_schedule(
    session: Session,
    schedule_id: str,
    trigger_config: dict[str, Any] | None = None,
    enabled: bool | None = None,
) -> Schedule:
    """Update schedule fields (partial updates supported).

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    schedule_id:
        The UUID of the schedule to update.
    trigger_config:
        Optional new trigger configuration.
    enabled:
        Optional new enabled status.

    Returns
    -------
    Schedule
        The updated Schedule object.

    Raises
    ------
    ScheduleNotFoundError
        If no schedule with the given ID exists.
    ScheduleValidationError
        If the new trigger configuration is invalid.
    """
    schedule = get_schedule(session, schedule_id)

    # Handle trigger_config update
    if trigger_config is not None:
        _validate_trigger_config(schedule.trigger_type, trigger_config)
        schedule.trigger_config = json.dumps(trigger_config)
        # TODO(W3T3.2): Re-register job with APScheduler (remove old, add new)

    # Handle enabled status update
    if enabled is not None and enabled != schedule.enabled:
        schedule.enabled = enabled
        # TODO(W3T3.2): Toggle schedule via TaskScheduler pause/resume methods

    session.flush()
    return schedule


def delete_schedule(session: Session, schedule_id: str) -> Schedule:
    """Delete schedule by ID.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    schedule_id:
        The UUID of the schedule to delete.

    Returns
    -------
    Schedule
        The deleted Schedule object (before deletion).

    Raises
    ------
    ScheduleNotFoundError
        If no schedule with the given ID exists.
    """
    schedule = get_schedule(session, schedule_id)

    # TODO(W3T3.2): Unregister job from APScheduler before deletion

    session.delete(schedule)
    session.flush()
    return schedule
