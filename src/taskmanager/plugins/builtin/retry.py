"""Retry plugin — automatically retries failed tasks with exponential backoff.

This plugin implements the on_after_execute hook to retry failed tasks based on
retry_count configuration in task metadata. Each retry creates a new Run record
and uses exponential backoff (2^attempt seconds).

Configuration in task.task_metadata:
{
    "retry_count": 3  # Number of retry attempts (default: 0, no retries)
}

Example:
    A task with retry_count=3 will be retried up to 3 times on failure:
    - First retry after 1 second (2^0)
    - Second retry after 2 seconds (2^1)
    - Third retry after 4 seconds (2^2)
"""

import time
from typing import TYPE_CHECKING

from pluggy import HookimplMarker
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from taskmanager.logging import get_logger
from taskmanager.models import RunStatus


if TYPE_CHECKING:
    from taskmanager.models import Run, Task

logger = get_logger(__name__)
hookimpl = HookimplMarker("taskmanager")


class RetryPlugin:
    """Plugin for automatic task retry with exponential backoff."""

    @hookimpl
    def on_after_execute(self, task: "Task", run: "Run") -> None:
        """Retry failed tasks based on retry_count in task metadata.

        This hook is called after task execution completes. If the run failed
        and retry_count is configured in task.task_metadata, this plugin will:
        1. Count existing failed runs for this task
        2. If retries remaining > 0, sleep with exponential backoff
        3. Create a new Run record and execute the task again

        Parameters
        ----------
        task:
            The Task that was executed.
        run:
            The completed Run with execution results.

        Notes
        -----
        - Only retries tasks with RunStatus.FAILED
        - Retry count is read from task.task_metadata['retry_count']
        - Exponential backoff formula: sleep(2 ** attempt) seconds
        - Each retry creates a new Run record linked to the same task
        - Stops when max retries reached or task succeeds
        """
        # Only retry if the run failed
        if run.status != RunStatus.FAILED:
            return

        # Check if retry is configured in task metadata
        if not task.task_metadata or "retry_count" not in task.task_metadata:
            return

        max_retries = task.task_metadata.get("retry_count", 0)
        if max_retries <= 0:
            return

        # Get the DB session from the SQLAlchemy object
        db = self._get_session(run)
        if db is None:
            logger.error(
                "retry.no_session",
                task_id=task.id,
                task_name=task.name,
                run_id=run.id,
                msg="Cannot retry: no database session available",
            )
            return

        # Count how many failed runs exist for this task (including current one)
        failed_count = (
            db.query(type(run))
            .filter_by(task_id=task.id, status=RunStatus.FAILED)
            .count()
        )

        # Calculate attempt number (0-indexed: 0 = first retry, 1 = second, etc.)
        attempt = failed_count - 1  # Subtract 1 because current run is already counted

        if attempt >= max_retries:
            logger.info(
                "retry.exhausted",
                task_id=task.id,
                task_name=task.name,
                run_id=run.id,
                attempt=attempt,
                max_retries=max_retries,
                msg=f"Max retries ({max_retries}) exhausted",
            )
            return

        # Exponential backoff: 2^attempt seconds (1s, 2s, 4s, 8s, ...)
        backoff_seconds = 2**attempt
        logger.info(
            "retry.waiting",
            task_id=task.id,
            task_name=task.name,
            run_id=run.id,
            attempt=attempt,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            msg=f"Retrying task (attempt {attempt + 1}/{max_retries}) after {backoff_seconds}s",
        )

        time.sleep(backoff_seconds)

        # Execute the task again - this will create a new Run record
        # Import here to avoid circular dependency
        from taskmanager.executor import execute_task  # noqa: PLC0415

        logger.info(
            "retry.executing",
            task_id=task.id,
            task_name=task.name,
            parent_run_id=run.id,
            attempt=attempt + 1,
            msg=f"Executing retry attempt {attempt + 1}/{max_retries}",
        )

        try:
            new_run = execute_task(task, db)
            logger.info(
                "retry.completed",
                task_id=task.id,
                task_name=task.name,
                parent_run_id=run.id,
                new_run_id=new_run.id,
                new_run_status=new_run.status.value,
                attempt=attempt + 1,
                msg=f"Retry attempt {attempt + 1}/{max_retries} completed with status {new_run.status.value}",
            )
        except Exception:
            logger.exception(
                "retry.failed",
                task_id=task.id,
                task_name=task.name,
                parent_run_id=run.id,
                attempt=attempt + 1,
                msg=f"Retry attempt {attempt + 1}/{max_retries} raised exception",
            )

    def _get_session(self, obj: object) -> Session | None:
        """Extract SQLAlchemy session from an ORM object.

        Parameters
        ----------
        obj:
            A SQLAlchemy ORM object.

        Returns
        -------
        Session | None
            The SQLAlchemy session if available, None otherwise.
        """
        try:
            obj_inspect = inspect(obj)
            # SQLAlchemy inspect returns InstanceState which may have .session
            if obj_inspect is None or not hasattr(obj_inspect, "session"):
                return None
            session = obj_inspect.session
            # session can be Session or None
            return session if isinstance(session, Session) else None
        except Exception:
            return None


# Export a singleton instance for pluggy to register
retry_plugin = RetryPlugin()
