"""Task service layer — pure business logic for task operations.

This module provides CRUD operations for tasks, decoupled from
CLI and API frameworks. All functions use session dependency injection.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from taskmanager.exceptions import DuplicateTaskError, TaskNotFoundError
from taskmanager.models import Task


def create_task(
    session: Session,
    name: str,
    command: str,
    description: str | None = None,
    shell: str = "/bin/sh",
) -> Task:
    """Create and persist a new task.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    name:
        Unique name for the task.
    command:
        Shell command to execute.
    description:
        Optional description of the task.
    shell:
        Shell to use for command execution (default: /bin/sh).

    Returns
    -------
    Task
        The created Task object.

    Raises
    ------
    DuplicateTaskError
        If a task with the same name already exists.
    """
    # Check for duplicate name
    existing = get_task_by_name(session, name)
    if existing is not None:
        raise DuplicateTaskError(name)

    task = Task(
        name=name,
        command=command,
        description=description,
        shell=shell,
    )
    session.add(task)
    session.flush()  # Flush to get the generated ID
    return task


def get_task(session: Session, task_id: str) -> Task:
    """Retrieve task by ID.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    task_id:
        The UUID of the task to retrieve.

    Returns
    -------
    Task
        The retrieved Task object.

    Raises
    ------
    TaskNotFoundError
        If no task with the given ID exists.
    """
    stmt = select(Task).where(Task.id == task_id)
    result = session.execute(stmt)
    task = result.scalar_one_or_none()

    if task is None:
        raise TaskNotFoundError(task_id)

    return task


def get_task_by_name(session: Session, name: str) -> Task | None:
    """Retrieve task by name.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    name:
        The name of the task to retrieve.

    Returns
    -------
    Task | None
        The Task object if found, None otherwise.
    """
    stmt = select(Task).where(Task.name == name)
    result = session.execute(stmt)
    return result.scalar_one_or_none()


def list_tasks(
    session: Session,
    name_contains: str | None = None,
) -> list[Task]:
    """List all tasks with optional name filtering.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    name_contains:
        Optional substring to filter task names (case-insensitive).

    Returns
    -------
    list[Task]
        List of Task objects matching the filter criteria.
        Returns empty list if no matches.
    """
    stmt = select(Task)

    if name_contains is not None:
        # Case-insensitive partial match
        pattern = f"%{name_contains}%"
        stmt = stmt.where(Task.name.ilike(pattern))

    result = session.execute(stmt)
    return list(result.scalars().all())


def update_task(
    session: Session,
    task_id: str,
    **updates: str,
) -> Task:
    """Update task fields (partial updates supported).

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    task_id:
        The UUID of the task to update.
    **updates:
        Field names and values to update.
        Supported fields: name, command, description, shell.

    Returns
    -------
    Task
        The updated Task object.

    Raises
    ------
    TaskNotFoundError
        If no task with the given ID exists.
    DuplicateTaskError
        If updating the name to one that already exists.
    """
    task = get_task(session, task_id)

    # Check for duplicate name if name is being updated
    if "name" in updates and updates["name"] != task.name:
        name_value = updates["name"]
        existing = get_task_by_name(session, name_value)
        if existing is not None:
            raise DuplicateTaskError(name_value)

    # Apply updates
    for field, value in updates.items():
        if hasattr(task, field):
            setattr(task, field, value)

    session.flush()
    return task


def delete_task(session: Session, task_id: str) -> Task:
    """Delete task by ID.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    task_id:
        The UUID of the task to delete.

    Returns
    -------
    Task
        The deleted Task object (before deletion).

    Raises
    ------
    TaskNotFoundError
        If no task with the given ID exists.
    """
    task = get_task(session, task_id)
    session.delete(task)
    session.flush()
    return task
