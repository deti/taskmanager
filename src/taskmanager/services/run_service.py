"""Run service layer — pure business logic for run operations.

This module provides read operations for task runs, decoupled from
CLI and API frameworks. All functions use session dependency injection.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from taskmanager.exceptions import RunNotFoundError
from taskmanager.models import Run, RunStatus, Task


def list_runs(
    session: Session,
    task_id: str | None = None,
    status: RunStatus | None = None,
    limit: int | None = None,
) -> list[Run]:
    """List runs with optional filters.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    task_id:
        Optional task ID to filter runs (foreign key to tasks.id).
    status:
        Optional status to filter runs (RunStatus enum).
    limit:
        Optional maximum number of runs to return.

    Returns
    -------
    list[Run]
        List of Run objects matching the filter criteria, ordered by
        started_at DESC (most recent first). Returns empty list if no matches.
    """
    stmt = select(Run)

    if task_id is not None:
        stmt = stmt.where(Run.task_id == task_id)

    if status is not None:
        stmt = stmt.where(Run.status == status)

    # Order by started_at DESC (most recent first)
    stmt = stmt.order_by(Run.started_at.desc())

    if limit is not None:
        stmt = stmt.limit(limit)

    result = session.execute(stmt)
    return list(result.scalars().all())


def get_run(session: Session, run_id: str) -> Run:
    """Get a run by ID.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    run_id:
        The UUID of the run to retrieve.

    Returns
    -------
    Run
        The retrieved Run object.

    Raises
    ------
    RunNotFoundError
        If no run with the given ID exists.
    """
    stmt = select(Run).where(Run.id == run_id)
    result = session.execute(stmt)
    run = result.scalar_one_or_none()

    if run is None:
        raise RunNotFoundError(run_id)

    return run


def get_runs_for_task(session: Session, task_name: str) -> list[Run]:
    """Get all runs for a task by task name.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    task_name:
        The name of the task to retrieve runs for.

    Returns
    -------
    list[Run]
        List of Run objects for the task, ordered by started_at DESC
        (most recent first). Returns empty list if task has no runs.

    Notes
    -----
    This function performs a join between runs and tasks tables to
    look up runs by task name rather than task_id.
    """
    stmt = (
        select(Run)
        .join(Task, Run.task_id == Task.id)
        .where(Task.name == task_name)
        .order_by(Run.started_at.desc())
    )

    result = session.execute(stmt)
    return list(result.scalars().all())
