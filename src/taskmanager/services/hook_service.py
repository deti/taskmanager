"""Hook service layer — business logic for hook CRUD operations.

This module provides CRUD operations for hooks, including validation of
action_config JSON schemas and task_filter foreign keys.
"""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from taskmanager.exceptions import (
    DuplicateHookError,
    HookNotFoundError,
    HookValidationError,
    TaskNotFoundError,
)
from taskmanager.models import ActionType, Hook, Task


def _validate_action_config(action_type: ActionType, action_config: str) -> None:
    """Validate action_config JSON schema for the given action type.

    Parameters
    ----------
    action_type:
        The action type enum.
    action_config:
        The JSON string to validate.

    Raises
    ------
    HookValidationError
        If the JSON is invalid or doesn't match the expected schema.
    """
    try:
        config = json.loads(action_config)
    except json.JSONDecodeError as exc:
        raise HookValidationError(f"Invalid JSON in action_config: {exc}") from exc

    if not isinstance(config, dict):
        raise HookValidationError("action_config must be a JSON object")

    # Validate schema based on action type
    if action_type == ActionType.SHELL:
        if "command" not in config:
            raise HookValidationError(
                "SHELL action requires 'command' field in action_config"
            )
        if not isinstance(config["command"], str):
            raise HookValidationError("SHELL 'command' must be a string")
        if not config["command"].strip():
            raise HookValidationError("SHELL 'command' cannot be empty")

    elif action_type == ActionType.WEBHOOK:
        if "url" not in config:
            raise HookValidationError(
                "WEBHOOK action requires 'url' field in action_config"
            )
        if not isinstance(config["url"], str):
            raise HookValidationError("WEBHOOK 'url' must be a string")
        if not config["url"].strip():
            raise HookValidationError("WEBHOOK 'url' cannot be empty")

    elif action_type == ActionType.LOG:
        # LOG is flexible — any valid JSON object is acceptable
        pass


def create_hook(
    session: Session,
    name: str,
    event_type: str,
    action_type: ActionType,
    action_config: str,
    task_filter: str | None = None,
    enabled: bool = True,
) -> Hook:
    """Create and persist a new hook.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    name:
        Unique name for the hook.
    event_type:
        Event type to listen for (e.g., "task.completed").
    action_type:
        Type of action to execute (SHELL, WEBHOOK, LOG).
    action_config:
        JSON string with action configuration.
    task_filter:
        Optional task ID to filter events (None = global hook).
    enabled:
        Whether the hook is enabled (default: True).

    Returns
    -------
    Hook
        The created Hook object.

    Raises
    ------
    DuplicateHookError
        If a hook with the same name already exists.
    HookValidationError
        If action_config JSON is invalid or doesn't match schema.
    TaskNotFoundError
        If task_filter references a non-existent task.
    """
    # Validate name is not empty
    if not name or not name.strip():
        raise HookValidationError("Hook name cannot be empty")

    # Validate event_type is not empty
    if not event_type or not event_type.strip():
        raise HookValidationError("event_type cannot be empty")

    # Check for duplicate name
    existing = get_hook_by_name(session, name)
    if existing is not None:
        raise DuplicateHookError(name)

    # Validate task_filter FK if provided
    if task_filter is not None:
        stmt = select(Task).where(Task.id == task_filter)
        result = session.execute(stmt)
        task = result.scalar_one_or_none()
        if task is None:
            raise TaskNotFoundError(task_filter)

    # Validate action_config JSON schema
    _validate_action_config(action_type, action_config)

    hook = Hook(
        name=name,
        event_type=event_type,
        action_type=action_type,
        action_config=action_config,
        task_filter=task_filter,
        enabled=enabled,
    )
    session.add(hook)
    session.flush()
    return hook


def get_hook_by_name(session: Session, name: str) -> Hook | None:
    """Retrieve hook by name.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    name:
        The name of the hook to retrieve.

    Returns
    -------
    Hook | None
        The Hook object if found, None otherwise.
    """
    stmt = select(Hook).where(Hook.name == name)
    result = session.execute(stmt)
    return result.scalar_one_or_none()


def get_hook(session: Session, name: str) -> Hook:
    """Retrieve hook by name.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    name:
        The name of the hook to retrieve.

    Returns
    -------
    Hook
        The retrieved Hook object.

    Raises
    ------
    HookNotFoundError
        If no hook with the given name exists.
    """
    hook = get_hook_by_name(session, name)
    if hook is None:
        raise HookNotFoundError(name)
    return hook


def list_hooks(
    session: Session,
    enabled: bool | None = None,
) -> list[Hook]:
    """List all hooks with optional filtering by enabled status.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    enabled:
        Optional filter for enabled status (None = all hooks).

    Returns
    -------
    list[Hook]
        List of Hook objects matching the filter criteria.
        Returns empty list if no matches.
    """
    stmt = select(Hook)

    if enabled is not None:
        stmt = stmt.where(Hook.enabled == enabled)

    result = session.execute(stmt)
    return list(result.scalars().all())


# Sentinel for optional fields in update
_UNSET = object()


def update_hook(
    session: Session,
    name: str,
    new_name: Any = _UNSET,
    event_type: Any = _UNSET,
    action_type: Any = _UNSET,
    action_config: Any = _UNSET,
    task_filter: Any = _UNSET,
    enabled: Any = _UNSET,
) -> Hook:
    """Update hook fields (partial updates supported).

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    name:
        The name of the hook to update.
    new_name:
        New name for the hook (optional).
    event_type:
        New event type (optional).
    action_type:
        New action type (optional).
    action_config:
        New action config JSON (optional).
    task_filter:
        New task filter (optional, None = global).
    enabled:
        New enabled status (optional).

    Returns
    -------
    Hook
        The updated Hook object.

    Raises
    ------
    HookNotFoundError
        If no hook with the given name exists.
    DuplicateHookError
        If updating the name to one that already exists.
    HookValidationError
        If action_config is invalid.
    TaskNotFoundError
        If task_filter references a non-existent task.
    """
    hook = get_hook(session, name)

    # Check for duplicate name if name is being updated
    if new_name is not _UNSET and new_name != hook.name:
        if not new_name or not new_name.strip():
            raise HookValidationError("Hook name cannot be empty")
        existing = get_hook_by_name(session, new_name)
        if existing is not None:
            raise DuplicateHookError(new_name)
        hook.name = new_name

    # Validate and update event_type
    if event_type is not _UNSET:
        if not event_type or not event_type.strip():
            raise HookValidationError("event_type cannot be empty")
        hook.event_type = event_type

    # Update action_type (will validate config below if either changes)
    if action_type is not _UNSET:
        hook.action_type = action_type

    # Update action_config
    if action_config is not _UNSET:
        hook.action_config = action_config

    # Validate action_config if action_type or action_config changed
    if action_type is not _UNSET or action_config is not _UNSET:
        _validate_action_config(hook.action_type, hook.action_config)

    # Validate and update task_filter
    if task_filter is not _UNSET:
        if task_filter is not None:
            stmt = select(Task).where(Task.id == task_filter)
            result = session.execute(stmt)
            task = result.scalar_one_or_none()
            if task is None:
                raise TaskNotFoundError(task_filter)
        hook.task_filter = task_filter

    # Update enabled
    if enabled is not _UNSET:
        hook.enabled = enabled

    session.flush()
    return hook


def delete_hook(session: Session, name: str) -> Hook:
    """Delete hook by name.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    name:
        The name of the hook to delete.

    Returns
    -------
    Hook
        The deleted Hook object (before deletion).

    Raises
    ------
    HookNotFoundError
        If no hook with the given name exists.
    """
    hook = get_hook(session, name)
    session.delete(hook)
    session.flush()
    return hook


def enable_hook(session: Session, name: str) -> Hook:
    """Enable a hook by name.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    name:
        The name of the hook to enable.

    Returns
    -------
    Hook
        The updated Hook object.

    Raises
    ------
    HookNotFoundError
        If no hook with the given name exists.
    """
    hook = get_hook(session, name)
    hook.enabled = True
    session.flush()
    return hook


def disable_hook(session: Session, name: str) -> Hook:
    """Disable a hook by name.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    name:
        The name of the hook to disable.

    Returns
    -------
    Hook
        The updated Hook object.

    Raises
    ------
    HookNotFoundError
        If no hook with the given name exists.
    """
    hook = get_hook(session, name)
    hook.enabled = False
    session.flush()
    return hook
