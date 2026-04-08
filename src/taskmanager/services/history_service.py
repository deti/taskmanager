"""History service layer — business logic for run history management.

This module provides operations for pruning old run records and calculating
execution statistics. All functions use session dependency injection.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from taskmanager.models import Run, RunStatus, Task
from taskmanager.settings import get_settings


def prune_runs(
    session: Session,
    older_than_days: int | None = None,
    dry_run: bool = False,
) -> int:
    """Delete runs older than specified retention period.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    older_than_days:
        Number of days to retain runs. If None, uses
        settings.history_retention_days as default.
    dry_run:
        If True, count runs that would be deleted without actually
        deleting them.

    Returns
    -------
    int
        Number of runs deleted (or would be deleted in dry-run mode).

    Notes
    -----
    Deletion is based on the `started_at` field. Runs with
    `started_at < (now - retention_days)` are removed.
    """
    # Use default from settings if not specified
    if older_than_days is None:
        older_than_days = get_settings().history_retention_days

    # Calculate cutoff date
    cutoff_date = datetime.now(UTC) - timedelta(days=older_than_days)

    # Build query for runs older than cutoff
    stmt = select(Run).where(Run.started_at < cutoff_date)

    if dry_run:
        # Count without deleting
        result = session.execute(stmt)
        runs = list(result.scalars().all())
        return len(runs)

    # Delete and return count
    delete_stmt = delete(Run).where(Run.started_at < cutoff_date)
    result = session.execute(delete_stmt)
    session.commit()

    # SQLAlchemy 2.0 returns CursorResult which has rowcount attribute
    rowcount = getattr(result, "rowcount", None)
    return rowcount if rowcount is not None else 0


def get_stats(session: Session, task_id: str | None = None) -> dict[str, Any]:
    """Calculate execution statistics for runs.

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    task_id:
        Optional task ID to filter statistics. If None, returns
        global statistics across all tasks.

    Returns
    -------
    dict
        Dictionary containing:
        - total_runs (int): Total number of runs
        - success_rate (float): Percentage of successful runs (0-100)
        - avg_duration_ms (float | None): Average duration in milliseconds,
          or None if no runs have duration data
        - most_failed_tasks (list): Top 5 tasks by failure count (only when
          task_id is None). Each item is a dict with keys: task_name, failure_count

    Notes
    -----
    Success rate is calculated as (success_count / total_runs) * 100.
    Average duration only includes runs where duration_ms is not NULL.
    """
    # Base query
    base_query = select(Run)
    if task_id is not None:
        base_query = base_query.where(Run.task_id == task_id)

    # Total runs
    total_result = session.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total_runs = total_result.scalar() or 0

    # Success count
    success_query = base_query.where(Run.status == RunStatus.SUCCESS)
    success_result = session.execute(
        select(func.count()).select_from(success_query.subquery())
    )
    success_count = success_result.scalar() or 0

    # Calculate success rate
    success_rate = (success_count / total_runs * 100) if total_runs > 0 else 0.0

    # Average duration (only for runs with duration_ms not NULL)
    # Use the base_query's WHERE conditions directly
    avg_duration_stmt = select(func.avg(Run.duration_ms))
    if task_id is not None:
        avg_duration_stmt = avg_duration_stmt.where(Run.task_id == task_id)
    avg_duration_stmt = avg_duration_stmt.where(Run.duration_ms.is_not(None))

    avg_duration_result = session.execute(avg_duration_stmt)
    avg_duration_ms = avg_duration_result.scalar()

    # Most failed tasks (only for global stats)
    most_failed_tasks = []
    if task_id is None:
        # Query: group by task_id, count failed runs, join Task for names
        failed_tasks_query = (
            select(
                Task.name.label("task_name"),
                func.count(Run.id).label("failure_count"),
            )
            .select_from(Run)
            .join(Task, Run.task_id == Task.id)
            .where(Run.status == RunStatus.FAILED)
            .group_by(Task.id, Task.name)
            .order_by(func.count(Run.id).desc())
            .limit(5)
        )

        failed_result = session.execute(failed_tasks_query)
        most_failed_tasks = [
            {"task_name": row.task_name, "failure_count": row.failure_count}
            for row in failed_result
        ]

    return {
        "total_runs": total_runs,
        "success_rate": success_rate,
        "avg_duration_ms": avg_duration_ms,
        "most_failed_tasks": most_failed_tasks,
    }
