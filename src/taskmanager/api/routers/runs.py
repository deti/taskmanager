"""Run history endpoints for the TaskManager API.

This module provides REST endpoints for querying task execution history:
- List runs with optional filters (task_id, status, limit)
- Get run details by ID
- Get run logs (stdout/stderr) by ID
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from taskmanager.api.deps import get_db
from taskmanager.api.schemas import PaginatedResponse, RunLogsResponse, RunResponse
from taskmanager.models import RunStatus
from taskmanager.services import run_service


router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get(
    "",
    response_model=PaginatedResponse[RunResponse],
    summary="List task runs",
    description="Retrieve a list of task runs with optional filtering by task_id and status. "
    "Results are ordered by started_at DESC (most recent first). "
    "Default limit is 20.",
)
async def list_runs(
    task_id: str | None = Query(None, description="Filter by task ID (UUID)"),
    status: RunStatus | None = Query(None, description="Filter by run status"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of runs to return"),
    db: Session = Depends(get_db),
) -> PaginatedResponse[RunResponse]:
    """List runs with optional filters.

    Args:
        task_id: Optional task ID to filter runs (UUID string).
        status: Optional status to filter runs (RunStatus enum).
        limit: Maximum number of runs to return (default: 20, max: 100).
        db: Database session from dependency injection.

    Returns:
        PaginatedResponse containing run list and pagination metadata.

    Example:
        GET /api/runs?task_id=123e4567-e89b-12d3-a456-426614174000&status=success&limit=10
        Returns up to 10 successful runs for the specified task.
    """
    # Query runs with filters
    runs = run_service.list_runs(
        session=db,
        task_id=task_id,
        status=status,
        limit=limit,
    )

    # Convert to response models
    run_responses = [RunResponse.model_validate(run) for run in runs]

    # Note: For true pagination, we'd need total count and page/page_size.
    # The current service API returns filtered results up to limit,
    # so we return them with total=len(runs), page=1, page_size=limit.
    return PaginatedResponse(
        items=run_responses,
        total=len(run_responses),
        page=1,
        page_size=limit,
    )


@router.get(
    "/{run_id}",
    response_model=RunResponse,
    summary="Get run details",
    description="Retrieve details for a specific run by ID. "
    "Returns 404 Not Found if the run does not exist.",
)
async def get_run(
    run_id: str,
    db: Session = Depends(get_db),
) -> RunResponse:
    """Get run details by ID.

    Args:
        run_id: The UUID of the run to retrieve.
        db: Database session from dependency injection.

    Returns:
        RunResponse with the run details.

    Raises:
        RunNotFoundError: If no run with the given ID exists
            (handled by global exception handler → 404 Not Found).

    Example:
        GET /api/runs/abc12345-e89b-12d3-a456-426614174000
        Returns run details with status, exit_code, stdout, stderr, etc.
    """
    run = run_service.get_run(session=db, run_id=run_id)
    return RunResponse.model_validate(run)


@router.get(
    "/{run_id}/logs",
    response_model=RunLogsResponse,
    summary="Get run logs",
    description="Retrieve stdout and stderr for a specific run by ID. "
    "Returns 404 Not Found if the run does not exist.",
)
async def get_run_logs(
    run_id: str,
    db: Session = Depends(get_db),
) -> RunLogsResponse:
    """Get run logs (stdout and stderr) by ID.

    Args:
        run_id: The UUID of the run to retrieve logs for.
        db: Database session from dependency injection.

    Returns:
        RunLogsResponse with stdout and stderr strings.

    Raises:
        RunNotFoundError: If no run with the given ID exists
            (handled by global exception handler → 404 Not Found).

    Example:
        GET /api/runs/abc12345-e89b-12d3-a456-426614174000/logs
        Returns:
        {
            "stdout": "Task output here...",
            "stderr": "Any errors here..."
        }
    """
    run = run_service.get_run(session=db, run_id=run_id)
    return RunLogsResponse(stdout=run.stdout, stderr=run.stderr)
