"""Task CRUD endpoints for the TaskManager API.

This module provides REST endpoints for task management operations:
- List tasks with pagination
- Create new tasks
- Get task details
- Update existing tasks
- Delete tasks
- Execute tasks
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from taskmanager.api.deps import get_db
from taskmanager.api.schemas import (
    PaginatedResponse,
    RunResponse,
    TaskCreate,
    TaskResponse,
    TaskUpdate,
)
from taskmanager.executor import execute_task
from taskmanager.models import Task
from taskmanager.services import task_service


router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get(
    "",
    response_model=PaginatedResponse[TaskResponse],
    summary="List all tasks",
    description="Retrieve a paginated list of all tasks. "
    "Page numbers are 1-indexed. Maximum page size is 100.",
)
async def list_tasks(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(
        20, ge=1, le=100, description="Number of items per page (max: 100)"
    ),
    db: Session = Depends(get_db),
) -> PaginatedResponse[TaskResponse]:
    """List all tasks with pagination.

    Args:
        page: Page number (1-indexed, minimum: 1).
        page_size: Number of items per page (minimum: 1, maximum: 100).
        db: Database session from dependency injection.

    Returns:
        PaginatedResponse containing task list and pagination metadata.

    Example:
        GET /api/tasks?page=1&page_size=20
        Returns first 20 tasks with total count and pagination info.
    """
    # Calculate total count
    count_stmt = select(func.count()).select_from(Task)
    total = db.execute(count_stmt).scalar_one()

    # Calculate offset
    offset = (page - 1) * page_size

    # Query tasks with pagination
    stmt = select(Task).limit(page_size).offset(offset)
    result = db.execute(stmt)
    tasks = list(result.scalars().all())

    # Convert to response models
    task_responses = [TaskResponse.model_validate(task) for task in tasks]

    return PaginatedResponse(
        items=task_responses,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new task",
    description="Create a new task with a unique name and command. "
    "Returns 409 Conflict if a task with the same name already exists.",
)
async def create_task(
    task_data: TaskCreate,
    db: Session = Depends(get_db),
) -> TaskResponse:
    """Create a new task.

    Args:
        task_data: Task creation data (name, command, description, shell).
        db: Database session from dependency injection.

    Returns:
        TaskResponse with the created task details.

    Raises:
        DuplicateTaskError: If a task with the same name already exists
            (handled by global exception handler → 409 Conflict).

    Example:
        POST /api/tasks
        {
            "name": "backup-database",
            "command": "pg_dump mydb > backup.sql",
            "description": "Daily database backup",
            "shell": "/bin/bash"
        }
    """
    task = task_service.create_task(
        session=db,
        name=task_data.name,
        command=task_data.command,
        description=task_data.description,
        shell=task_data.shell,
    )

    return TaskResponse.model_validate(task)


@router.get(
    "/{task_id}",
    response_model=TaskResponse,
    summary="Get task details",
    description="Retrieve details for a specific task by ID. "
    "Returns 404 Not Found if the task does not exist.",
)
async def get_task(
    task_id: str,
    db: Session = Depends(get_db),
) -> TaskResponse:
    """Get task details by ID.

    Args:
        task_id: The UUID of the task to retrieve.
        db: Database session from dependency injection.

    Returns:
        TaskResponse with the task details.

    Raises:
        TaskNotFoundError: If no task with the given ID exists
            (handled by global exception handler → 404 Not Found).

    Example:
        GET /api/tasks/123e4567-e89b-12d3-a456-426614174000
        Returns task details with name, command, timestamps, etc.
    """
    task = task_service.get_task(session=db, task_id=task_id)
    return TaskResponse.model_validate(task)


@router.patch(
    "/{task_id}",
    response_model=TaskResponse,
    summary="Update a task",
    description="Update one or more fields of an existing task. "
    "Only provided fields are updated (partial update). "
    "Returns 404 Not Found if the task does not exist. "
    "Returns 409 Conflict if updating the name to one that already exists.",
)
async def update_task(
    task_id: str,
    task_data: TaskUpdate,
    db: Session = Depends(get_db),
) -> TaskResponse:
    """Update task fields (partial update).

    Args:
        task_id: The UUID of the task to update.
        task_data: Task update data (all fields optional).
        db: Database session from dependency injection.

    Returns:
        TaskResponse with the updated task details.

    Raises:
        TaskNotFoundError: If no task with the given ID exists
            (handled by global exception handler → 404 Not Found).
        DuplicateTaskError: If updating the name to one that already exists
            (handled by global exception handler → 409 Conflict).

    Example:
        PATCH /api/tasks/123e4567-e89b-12d3-a456-426614174000
        {
            "command": "pg_dump mydb > /backups/backup.sql",
            "description": "Daily database backup (updated path)"
        }
    """
    # Build updates dict with only provided fields (exclude_unset=True)
    updates = task_data.model_dump(exclude_unset=True)

    task = task_service.update_task(
        session=db,
        task_id=task_id,
        **updates,
    )

    return TaskResponse.model_validate(task)


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a task",
    description="Delete a task by ID. Returns 204 No Content on success. "
    "Returns 404 Not Found if the task does not exist.",
)
async def delete_task(
    task_id: str,
    db: Session = Depends(get_db),
) -> None:
    """Delete a task by ID.

    Args:
        task_id: The UUID of the task to delete.
        db: Database session from dependency injection.

    Returns:
        None (204 No Content).

    Raises:
        TaskNotFoundError: If no task with the given ID exists
            (handled by global exception handler → 404 Not Found).

    Example:
        DELETE /api/tasks/123e4567-e89b-12d3-a456-426614174000
        Returns 204 No Content on successful deletion.
    """
    task_service.delete_task(session=db, task_id=task_id)


@router.post(
    "/{task_id}/execute",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Execute a task",
    description="Trigger execution of a task. Returns 202 Accepted with run details. "
    "The task is executed asynchronously, and the run ID can be used to track progress. "
    "Returns 404 Not Found if the task does not exist.",
)
async def execute_task_endpoint(
    task_id: str,
    db: Session = Depends(get_db),
) -> RunResponse:
    """Execute a task and return run details.

    Args:
        task_id: The UUID of the task to execute.
        db: Database session from dependency injection.

    Returns:
        RunResponse with run ID, status, and execution metadata.

    Raises:
        TaskNotFoundError: If no task with the given ID exists
            (handled by global exception handler → 404 Not Found).

    Example:
        POST /api/tasks/123e4567-e89b-12d3-a456-426614174000/execute
        Returns 202 Accepted with run details:
        {
            "id": "abc12345-...",
            "task_id": "123e4567-...",
            "status": "running",
            "started_at": "2026-04-08T01:23:45Z",
            ...
        }
    """
    # Fetch task (raises TaskNotFoundError if not found)
    task = task_service.get_task(session=db, task_id=task_id)

    # Execute task and get run record
    run = execute_task(task=task, db=db)

    return RunResponse.model_validate(run)
