"""Export/Import service layer — business logic for data export and import.

This module provides operations for exporting tasks, schedules, and hooks to
YAML-friendly dictionaries and importing them back with conflict resolution.
All functions use session dependency injection.
"""

import json
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from taskmanager.exceptions import (
    DuplicateHookError,
    DuplicateScheduleError,
    DuplicateTaskError,
    TaskNotFoundError,
)
from taskmanager.models import ActionType, Hook, Schedule, Task, TriggerType
from taskmanager.services.hook_service import create_hook, get_hook_by_name, update_hook
from taskmanager.services.schedule_service import create_schedule, update_schedule
from taskmanager.services.task_service import (
    create_task,
    get_task_by_name,
    update_task,
)


def export_all(session: Session) -> dict[str, Any]:
    """Export all tasks, schedules, and hooks to a YAML-friendly dictionary.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.

    Returns
    -------
    dict
        Dictionary containing:
        - version (str): Export format version ("1.0")
        - exported_at (str): ISO8601 timestamp of export
        - tasks (list): List of task dictionaries
        - schedules (list): List of schedule dictionaries
        - hooks (list): List of hook dictionaries

    Notes
    -----
    The exported data excludes generated fields (IDs, timestamps) and uses
    task names instead of IDs for human readability and portability.
    Enums are serialized as strings.
    """
    # Query all entities
    tasks = session.execute(select(Task)).scalars().all()
    schedules = session.execute(select(Schedule)).scalars().all()
    hooks = session.execute(select(Hook)).scalars().all()

    # Build task name lookup for resolving foreign keys
    task_id_to_name = {task.id: task.name for task in tasks}

    # Export tasks
    tasks_data = []
    for task in tasks:
        task_dict = {
            "name": task.name,
            "command": task.command,
            "description": task.description,
            "shell": task.shell,
            "metadata": task.task_metadata,
        }
        tasks_data.append(task_dict)

    # Export schedules
    schedules_data = []
    for schedule in schedules:
        schedule_dict = {
            "task_name": task_id_to_name.get(schedule.task_id),
            "trigger_type": schedule.trigger_type.value,
            "trigger_config": schedule.trigger_config,
            "enabled": schedule.enabled,
        }
        schedules_data.append(schedule_dict)

    # Export hooks
    hooks_data = []
    for hook in hooks:
        hook_dict = {
            "name": hook.name,
            "event_type": hook.event_type,
            "task_filter_name": (
                task_id_to_name.get(hook.task_filter)
                if hook.task_filter is not None
                else None
            ),
            "action_type": hook.action_type.value,
            "action_config": hook.action_config,
            "enabled": hook.enabled,
        }
        hooks_data.append(hook_dict)

    # Build and return final export structure
    return {
        "version": "1.0",
        "exported_at": datetime.now(UTC).isoformat(),
        "tasks": tasks_data,
        "schedules": schedules_data,
        "hooks": hooks_data,
    }


def import_all(  # noqa: PLR0912, PLR0915
    session: Session,
    data: dict[str, Any],
    on_conflict: Literal["skip", "overwrite", "error"] = "error",
) -> dict[str, int]:
    """Import tasks, schedules, and hooks from YAML data with conflict resolution.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    data:
        Dictionary containing tasks, schedules, and hooks data
        (typically from YAML export).
    on_conflict:
        Strategy for handling existing entities:
        - "error": Raise exception on duplicate (default)
        - "skip": Skip existing entities silently
        - "overwrite": Update existing entities

    Returns
    -------
    dict
        Dictionary with import statistics:
        - tasks_created (int): Number of tasks created
        - tasks_updated (int): Number of tasks updated
        - tasks_skipped (int): Number of tasks skipped
        - schedules_created (int): Number of schedules created
        - schedules_updated (int): Number of schedules updated
        - schedules_skipped (int): Number of schedules skipped
        - hooks_created (int): Number of hooks created
        - hooks_updated (int): Number of hooks updated
        - hooks_skipped (int): Number of hooks skipped

    Raises
    ------
    ValueError
        If data structure is invalid or missing required keys.
    DuplicateTaskError
        If on_conflict="error" and duplicate task exists.
    DuplicateScheduleError
        If on_conflict="error" and duplicate schedule exists.
    DuplicateHookError
        If on_conflict="error" and duplicate hook exists.
    TaskNotFoundError
        If schedule or hook references non-existent task.

    Notes
    -----
    Import order: tasks → schedules → hooks (due to foreign key dependencies).
    Task names are resolved to task IDs during schedule and hook imports.
    """
    # Validate data structure
    if not isinstance(data, dict):
        msg = "Import data must be a dictionary"
        raise TypeError(msg)

    if "tasks" not in data:
        msg = "Import data missing required key: 'tasks'"
        raise ValueError(msg)

    if "schedules" not in data:
        msg = "Import data missing required key: 'schedules'"
        raise ValueError(msg)

    if "hooks" not in data:
        msg = "Import data missing required key: 'hooks'"
        raise ValueError(msg)

    # Initialize counters
    stats = {
        "tasks_created": 0,
        "tasks_updated": 0,
        "tasks_skipped": 0,
        "schedules_created": 0,
        "schedules_updated": 0,
        "schedules_skipped": 0,
        "hooks_created": 0,
        "hooks_updated": 0,
        "hooks_skipped": 0,
    }

    # Import tasks first (no dependencies)
    for task_data in data.get("tasks", []):
        name = task_data["name"]
        existing_task = get_task_by_name(session, name)

        if existing_task is not None:
            if on_conflict == "error":
                raise DuplicateTaskError(name)
            if on_conflict == "skip":
                stats["tasks_skipped"] += 1
                continue
            if on_conflict == "overwrite":
                # Update existing task
                update_task(
                    session,
                    existing_task.id,
                    name=task_data.get("name", existing_task.name),
                    command=task_data.get("command", existing_task.command),
                    description=task_data.get("description", existing_task.description),
                    shell=task_data.get("shell", existing_task.shell),
                )
                stats["tasks_updated"] += 1
        else:
            # Create new task
            create_task(
                session,
                name=task_data["name"],
                command=task_data["command"],
                description=task_data.get("description"),
                shell=task_data.get("shell", "/bin/sh"),
            )
            stats["tasks_created"] += 1

    # Commit tasks before importing schedules/hooks (for FK resolution)
    session.flush()

    # Import schedules second (depend on tasks)
    for schedule_data in data.get("schedules", []):
        task_name = schedule_data["task_name"]

        # Resolve task name to task ID
        task = get_task_by_name(session, task_name)
        if task is None:
            msg = f"Schedule references non-existent task: '{task_name}'"
            raise TaskNotFoundError(msg)

        # Parse trigger type enum
        trigger_type_str = schedule_data["trigger_type"]
        trigger_type = TriggerType(trigger_type_str)

        # Check for existing schedule (task_id + trigger_type)
        existing_schedule_stmt = select(Schedule).where(
            Schedule.task_id == task.id,
            Schedule.trigger_type == trigger_type,
        )
        existing_schedule = session.execute(existing_schedule_stmt).scalar_one_or_none()

        if existing_schedule is not None:
            if on_conflict == "error":
                raise DuplicateScheduleError(task.id, trigger_type.value)
            if on_conflict == "skip":
                stats["schedules_skipped"] += 1
                continue
            if on_conflict == "overwrite":
                # Update existing schedule
                # Parse trigger_config from JSON string to dict
                trigger_config_dict = json.loads(schedule_data.get("trigger_config"))
                update_schedule(
                    session,
                    existing_schedule.id,
                    trigger_config=trigger_config_dict,
                    enabled=schedule_data.get("enabled", existing_schedule.enabled),
                )
                stats["schedules_updated"] += 1
        else:
            # Create new schedule
            # Parse trigger_config from JSON string to dict
            trigger_config_dict = json.loads(schedule_data["trigger_config"])
            create_schedule(
                session,
                task_id=task.id,
                trigger_type=trigger_type,
                trigger_config=trigger_config_dict,
                enabled=schedule_data.get("enabled", True),
            )
            stats["schedules_created"] += 1

    # Import hooks third (may depend on tasks via task_filter)
    for hook_data in data.get("hooks", []):
        name = hook_data["name"]

        # Resolve task_filter_name to task_id (if present)
        task_filter_name = hook_data.get("task_filter_name")
        task_filter_id = None
        if task_filter_name is not None:
            task_filter = get_task_by_name(session, task_filter_name)
            if task_filter is None:
                msg = f"Hook references non-existent task: '{task_filter_name}'"
                raise TaskNotFoundError(msg)
            task_filter_id = task_filter.id

        # Parse action type enum
        action_type_str = hook_data["action_type"]
        action_type = ActionType(action_type_str)

        # Check for existing hook by name
        existing_hook = get_hook_by_name(session, name)

        if existing_hook is not None:
            if on_conflict == "error":
                raise DuplicateHookError(name)
            if on_conflict == "skip":
                stats["hooks_skipped"] += 1
                continue
            if on_conflict == "overwrite":
                # Update existing hook
                update_hook(
                    session,
                    name,
                    event_type=hook_data.get("event_type", existing_hook.event_type),
                    task_filter=task_filter_id,
                    action_type=action_type,
                    action_config=hook_data.get("action_config"),
                    enabled=hook_data.get("enabled", existing_hook.enabled),
                )
                stats["hooks_updated"] += 1
        else:
            # Create new hook
            create_hook(
                session,
                name=hook_data["name"],
                event_type=hook_data["event_type"],
                action_type=action_type,
                action_config=hook_data["action_config"],
                task_filter=task_filter_id,
                enabled=hook_data.get("enabled", True),
            )
            stats["hooks_created"] += 1

    return stats
