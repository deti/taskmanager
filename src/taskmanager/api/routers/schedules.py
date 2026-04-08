"""Schedule CRUD endpoints for the TaskManager API.

This module provides REST endpoints for schedule management operations:
- List schedules with optional filters
- Create new schedules
- Get schedule details
- Update existing schedules
- Delete schedules
- Enable/disable schedules
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from taskmanager.api.deps import get_db
from taskmanager.api.schemas import (
    ScheduleCreate,
    ScheduleResponse,
    ScheduleUpdate,
)
from taskmanager.services import schedule_service


router = APIRouter(prefix="/api/schedules", tags=["schedules"])


@router.get(
    "",
    response_model=list[ScheduleResponse],
    summary="List all schedules",
    description="Retrieve a list of all schedules with optional filtering by task_id and enabled status.",
)
async def list_schedules(
    task_id: str | None = Query(None, description="Filter by task ID (UUID)"),
    enabled: bool | None = Query(None, description="Filter by enabled status"),
    db: Session = Depends(get_db),
) -> list[ScheduleResponse]:
    """List all schedules with optional filters.

    Args:
        task_id: Optional task ID to filter schedules by (UUID string).
        enabled: Optional enabled status to filter by (true/false).
        db: Database session from dependency injection.

    Returns:
        List of ScheduleResponse objects matching the filter criteria.

    Example:
        GET /api/schedules?task_id=123e4567-e89b-12d3-a456-426614174000&enabled=true
        Returns all enabled schedules for the specified task.
    """
    schedules = schedule_service.list_schedules(
        session=db,
        task_id=task_id,
        enabled=enabled,
    )

    return [ScheduleResponse.model_validate(schedule) for schedule in schedules]


@router.post(
    "",
    response_model=ScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new schedule",
    description="Create a new schedule for a task with a specific trigger type and configuration. "
    "Returns 404 Not Found if the task does not exist. "
    "Returns 409 Conflict if a schedule with the same task_id and trigger_type already exists. "
    "Returns 422 Unprocessable Entity if the trigger configuration is invalid.",
)
async def create_schedule(
    schedule_data: ScheduleCreate,
    db: Session = Depends(get_db),
) -> ScheduleResponse:
    """Create a new schedule.

    Args:
        schedule_data: Schedule creation data (task_id, trigger_type, trigger_config, enabled).
        db: Database session from dependency injection.

    Returns:
        ScheduleResponse with the created schedule details.

    Raises:
        TaskNotFoundError: If the task with the given ID does not exist
            (handled by global exception handler → 404 Not Found).
        DuplicateScheduleError: If a schedule with the same task_id and trigger_type already exists
            (handled by global exception handler → 409 Conflict).
        ScheduleValidationError: If the trigger configuration is invalid
            (handled by global exception handler → 422 Unprocessable Entity).

    Example:
        POST /api/schedules
        {
            "task_id": "123e4567-e89b-12d3-a456-426614174000",
            "trigger_type": "cron",
            "trigger_config": {"cron": "0 2 * * *"},
            "enabled": true
        }
    """
    schedule = schedule_service.create_schedule(
        session=db,
        task_id=schedule_data.task_id,
        trigger_type=schedule_data.trigger_type,
        trigger_config=schedule_data.trigger_config,
        enabled=schedule_data.enabled,
    )

    return ScheduleResponse.model_validate(schedule)


@router.get(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    summary="Get schedule details",
    description="Retrieve details for a specific schedule by ID. "
    "Returns 404 Not Found if the schedule does not exist.",
)
async def get_schedule(
    schedule_id: str,
    db: Session = Depends(get_db),
) -> ScheduleResponse:
    """Get schedule details by ID.

    Args:
        schedule_id: The UUID of the schedule to retrieve.
        db: Database session from dependency injection.

    Returns:
        ScheduleResponse with the schedule details.

    Raises:
        ScheduleNotFoundError: If no schedule with the given ID exists
            (handled by global exception handler → 404 Not Found).

    Example:
        GET /api/schedules/abc12345-e89b-12d3-a456-426614174000
        Returns schedule details with task_id, trigger_type, trigger_config, etc.
    """
    schedule = schedule_service.get_schedule(session=db, schedule_id=schedule_id)
    return ScheduleResponse.model_validate(schedule)


@router.put(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    summary="Update a schedule",
    description="Update one or more fields of an existing schedule. "
    "Only provided fields are updated (partial update). "
    "Returns 404 Not Found if the schedule does not exist. "
    "Returns 422 Unprocessable Entity if the trigger configuration is invalid.",
)
async def update_schedule(
    schedule_id: str,
    schedule_data: ScheduleUpdate,
    db: Session = Depends(get_db),
) -> ScheduleResponse:
    """Update schedule fields (partial update).

    Args:
        schedule_id: The UUID of the schedule to update.
        schedule_data: Schedule update data (trigger_config and/or enabled).
        db: Database session from dependency injection.

    Returns:
        ScheduleResponse with the updated schedule details.

    Raises:
        ScheduleNotFoundError: If no schedule with the given ID exists
            (handled by global exception handler → 404 Not Found).
        ScheduleValidationError: If the trigger configuration is invalid
            (handled by global exception handler → 422 Unprocessable Entity).

    Example:
        PUT /api/schedules/abc12345-e89b-12d3-a456-426614174000
        {
            "trigger_config": {"cron": "0 3 * * *"},
            "enabled": false
        }
    """
    # Build updates dict with only provided fields (exclude_unset=True)
    updates = schedule_data.model_dump(exclude_unset=True)

    schedule = schedule_service.update_schedule(
        session=db,
        schedule_id=schedule_id,
        **updates,
    )

    return ScheduleResponse.model_validate(schedule)


@router.delete(
    "/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a schedule",
    description="Delete a schedule by ID. Returns 204 No Content on success. "
    "Returns 404 Not Found if the schedule does not exist.",
)
async def delete_schedule(
    schedule_id: str,
    db: Session = Depends(get_db),
) -> None:
    """Delete a schedule by ID.

    Args:
        schedule_id: The UUID of the schedule to delete.
        db: Database session from dependency injection.

    Returns:
        None (204 No Content).

    Raises:
        ScheduleNotFoundError: If no schedule with the given ID exists
            (handled by global exception handler → 404 Not Found).

    Example:
        DELETE /api/schedules/abc12345-e89b-12d3-a456-426614174000
        Returns 204 No Content on successful deletion.
    """
    schedule_service.delete_schedule(session=db, schedule_id=schedule_id)


@router.post(
    "/{schedule_id}/enable",
    response_model=ScheduleResponse,
    summary="Enable a schedule",
    description="Enable a schedule by ID. Sets enabled=True. "
    "Returns 404 Not Found if the schedule does not exist.",
)
async def enable_schedule(
    schedule_id: str,
    db: Session = Depends(get_db),
) -> ScheduleResponse:
    """Enable a schedule by ID.

    Args:
        schedule_id: The UUID of the schedule to enable.
        db: Database session from dependency injection.

    Returns:
        ScheduleResponse with the updated schedule details.

    Raises:
        ScheduleNotFoundError: If no schedule with the given ID exists
            (handled by global exception handler → 404 Not Found).

    Example:
        POST /api/schedules/abc12345-e89b-12d3-a456-426614174000/enable
        Returns updated schedule with enabled=True.
    """
    schedule = schedule_service.update_schedule(
        session=db,
        schedule_id=schedule_id,
        enabled=True,
    )
    return ScheduleResponse.model_validate(schedule)


@router.post(
    "/{schedule_id}/disable",
    response_model=ScheduleResponse,
    summary="Disable a schedule",
    description="Disable a schedule by ID. Sets enabled=False. "
    "Returns 404 Not Found if the schedule does not exist.",
)
async def disable_schedule(
    schedule_id: str,
    db: Session = Depends(get_db),
) -> ScheduleResponse:
    """Disable a schedule by ID.

    Args:
        schedule_id: The UUID of the schedule to disable.
        db: Database session from dependency injection.

    Returns:
        ScheduleResponse with the updated schedule details.

    Raises:
        ScheduleNotFoundError: If no schedule with the given ID exists
            (handled by global exception handler → 404 Not Found).

    Example:
        POST /api/schedules/abc12345-e89b-12d3-a456-426614174000/disable
        Returns updated schedule with enabled=False.
    """
    schedule = schedule_service.update_schedule(
        session=db,
        schedule_id=schedule_id,
        enabled=False,
    )
    return ScheduleResponse.model_validate(schedule)
