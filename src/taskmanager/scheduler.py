"""Task scheduler — APScheduler integration for recurring task execution.

This module provides the TaskScheduler class which manages scheduled task
execution using APScheduler's BackgroundScheduler. It supports three trigger
types: CRON, INTERVAL, and ONCE (one-time).

The scheduler uses SQLAlchemyJobStore for persistence, allowing jobs to
survive application restarts.
"""

import json
from datetime import datetime
from typing import Any

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore  # type: ignore[import-untyped]
from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]
from apscheduler.triggers.date import DateTrigger  # type: ignore[import-untyped]
from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-untyped]
from sqlalchemy.orm import Session

from taskmanager.database import get_db
from taskmanager.executor import execute_task
from taskmanager.logging import get_logger
from taskmanager.models import Schedule, Task, TriggerType
from taskmanager.settings import get_settings


logger = get_logger(__name__)


def _execute_task_job(task_id: str) -> None:
    """Execute a task in a scheduled job.

    This is a module-level function called by APScheduler. It creates a fresh
    database session and executes the task.

    Parameters
    ----------
    task_id:
        The ID of the task to execute.
    """
    with get_db() as db:
        task = db.query(Task).filter(Task.id == task_id).first()
        if task is None:
            logger.error("scheduler.task_not_found", task_id=task_id)
            return

        logger.info("scheduler.job_executing", task_id=task_id, task_name=task.name)
        execute_task(task, db)


class SchedulerError(Exception):
    """Base exception for scheduler errors."""


class InvalidTriggerConfigError(SchedulerError):
    """Raised when trigger_config JSON is invalid or missing required fields."""

    def __init__(self, message: str, schedule_id: str | None = None) -> None:
        self.message = message
        self.schedule_id = schedule_id
        super().__init__(message)


# Singleton instance
_scheduler_instance: "TaskScheduler | None" = None


class TaskScheduler:
    """Manages scheduled task execution with APScheduler.

    This class provides a singleton interface to APScheduler's BackgroundScheduler.
    It handles job persistence via SQLAlchemyJobStore and supports adding, removing,
    pausing, and resuming scheduled tasks.

    The scheduler supports three trigger types:
    - CRON: Cron-style scheduling (e.g., "*/5 * * * *")
    - INTERVAL: Fixed interval scheduling (e.g., every 30 minutes)
    - ONCE: One-time execution at a specific datetime

    Example:
        scheduler = TaskScheduler.get_instance()
        scheduler.start()

        # Add a cron schedule
        schedule = Schedule(
            task_id=task.id,
            trigger_type=TriggerType.CRON,
            trigger_config='{"cron": "*/5 * * * *"}',
        )
        with get_db() as db:
            scheduler.add_schedule(schedule, db)
    """

    def __init__(self) -> None:
        """Initialize the scheduler with SQLAlchemy job store.

        Note: Use get_instance() instead of calling this directly.
        """
        settings = get_settings()

        # Configure job store (table is auto-created by SQLAlchemyJobStore)
        jobstores = {
            "default": SQLAlchemyJobStore(
                url=settings.db_url,
                tablename="apscheduler_jobs",
            )
        }

        self._scheduler = BackgroundScheduler(
            jobstores=jobstores,
            job_defaults={
                "coalesce": False,  # Run all missed executions
                "max_instances": 1,  # One instance per job at a time
            },
        )

        logger.info("scheduler.initialized", db_url=settings.db_url)

    @classmethod
    def get_instance(cls) -> "TaskScheduler":
        """Get the singleton scheduler instance.

        Returns:
            The singleton TaskScheduler instance.
        """
        global _scheduler_instance  # noqa: PLW0603
        if _scheduler_instance is None:
            _scheduler_instance = cls()
        return _scheduler_instance

    def start(self) -> None:
        """Start the scheduler (non-blocking).

        This starts the background scheduler thread. Jobs will begin
        executing according to their triggers.
        """
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("scheduler.started")

    def stop(self, wait: bool = True) -> None:
        """Stop the scheduler gracefully.

        Parameters
        ----------
        wait:
            If True, wait for running jobs to complete before stopping.
        """
        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)
            logger.info("scheduler.stopped", wait=wait)

    def add_schedule(self, schedule: Schedule, db: Session) -> None:
        """Add a schedule to APScheduler and update next_run_at.

        Parses the schedule's trigger_config JSON and creates the appropriate
        APScheduler trigger. After adding the job, updates schedule.next_run_at
        from APScheduler's calculated next run time.

        Parameters
        ----------
        schedule:
            The Schedule model instance to add. Must have valid trigger_config.
        db:
            SQLAlchemy session for database operations.

        Raises
        ------
        InvalidTriggerConfigError:
            If trigger_config is invalid JSON or missing required fields.
        """
        # Parse trigger config
        try:
            config = json.loads(schedule.trigger_config)
        except json.JSONDecodeError as e:
            msg = f"Invalid JSON in trigger_config: {e}"
            raise InvalidTriggerConfigError(msg, schedule.id) from e

        # Build trigger based on type
        trigger = self._build_trigger(schedule.trigger_type, config, schedule.id)

        # Fetch the task to pass to the job function
        task = db.query(Task).filter(Task.id == schedule.task_id).first()
        if task is None:
            msg = f"Task {schedule.task_id} not found for schedule {schedule.id}"
            raise SchedulerError(msg)

        # Add job to APScheduler
        job = self._scheduler.add_job(
            func=_execute_task_job,
            trigger=trigger,
            id=schedule.id,
            args=[schedule.task_id],
            replace_existing=True,
        )

        # Update next_run_at from APScheduler
        if job.next_run_time:
            schedule.next_run_at = job.next_run_time

        db.commit()

        logger.info(
            "scheduler.job_added",
            schedule_id=schedule.id,
            task_id=schedule.task_id,
            trigger_type=schedule.trigger_type.value,
            next_run_at=schedule.next_run_at,
        )

    def _build_trigger(
        self, trigger_type: TriggerType, config: dict[str, Any], schedule_id: str
    ) -> CronTrigger | IntervalTrigger | DateTrigger:
        """Build an APScheduler trigger from config.

        Parameters
        ----------
        trigger_type:
            The type of trigger (CRON, INTERVAL, or ONCE).
        config:
            The parsed trigger_config dictionary.
        schedule_id:
            The schedule ID for error reporting.

        Returns
        -------
        CronTrigger | IntervalTrigger | DateTrigger
            The constructed APScheduler trigger.

        Raises
        ------
        InvalidTriggerConfigError:
            If config is missing required fields or has invalid values.
        """
        if trigger_type == TriggerType.CRON:
            cron_expr = config.get("cron")
            if not cron_expr:
                msg = "CRON trigger requires 'cron' field in trigger_config"
                raise InvalidTriggerConfigError(msg, schedule_id)

            # Parse cron expression (standard 5-field format)
            parts = cron_expr.split()
            if len(parts) != 5:
                msg = f"Invalid cron expression '{cron_expr}' — expected 5 fields"
                raise InvalidTriggerConfigError(msg, schedule_id)

            minute, hour, day, month, day_of_week = parts
            return CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
            )

        if trigger_type == TriggerType.INTERVAL:
            interval_config = config.get("interval")
            if not interval_config:
                msg = "INTERVAL trigger requires 'interval' field in trigger_config"
                raise InvalidTriggerConfigError(msg, schedule_id)

            # Convert interval config to kwargs for IntervalTrigger
            # Supports: seconds, minutes, hours, days, weeks
            valid_units = {"seconds", "minutes", "hours", "days", "weeks"}
            kwargs = {k: v for k, v in interval_config.items() if k in valid_units}

            if not kwargs:
                msg = f"INTERVAL trigger requires at least one time unit: {valid_units}"
                raise InvalidTriggerConfigError(msg, schedule_id)

            return IntervalTrigger(**kwargs)

        if trigger_type == TriggerType.ONCE:
            once_str = config.get("once")
            if not once_str:
                msg = "ONCE trigger requires 'once' field in trigger_config"
                raise InvalidTriggerConfigError(msg, schedule_id)

            try:
                run_date = datetime.fromisoformat(once_str)
            except ValueError as e:
                msg = f"Invalid datetime format '{once_str}' — expected ISO 8601"
                raise InvalidTriggerConfigError(msg, schedule_id) from e

            return DateTrigger(run_date=run_date)

        msg = f"Unsupported trigger type: {trigger_type}"
        raise InvalidTriggerConfigError(msg, schedule_id)

    def remove_schedule(self, schedule_id: str) -> None:
        """Remove a schedule from APScheduler.

        Parameters
        ----------
        schedule_id:
            The ID of the schedule to remove.
        """
        try:
            self._scheduler.remove_job(schedule_id)
            logger.info("scheduler.job_removed", schedule_id=schedule_id)
        except Exception as e:
            logger.warning(
                "scheduler.job_remove_failed",
                schedule_id=schedule_id,
                error=str(e),
            )

    def pause_schedule(self, schedule_id: str, db: Session) -> None:
        """Pause a schedule and update the database.

        Parameters
        ----------
        schedule_id:
            The ID of the schedule to pause.
        db:
            SQLAlchemy session for database operations.
        """
        try:
            self._scheduler.pause_job(schedule_id)
            logger.info("scheduler.job_paused", schedule_id=schedule_id)

            # Update database
            schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
            if schedule:
                schedule.enabled = False
                db.commit()

        except Exception as e:
            logger.warning(
                "scheduler.job_pause_failed",
                schedule_id=schedule_id,
                error=str(e),
            )

    def resume_schedule(self, schedule_id: str, db: Session) -> None:
        """Resume a paused schedule and update the database.

        Parameters
        ----------
        schedule_id:
            The ID of the schedule to resume.
        db:
            SQLAlchemy session for database operations.
        """
        try:
            self._scheduler.resume_job(schedule_id)
            logger.info("scheduler.job_resumed", schedule_id=schedule_id)

            # Update database
            schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
            if schedule:
                schedule.enabled = True
                db.commit()

        except Exception as e:
            logger.warning(
                "scheduler.job_resume_failed",
                schedule_id=schedule_id,
                error=str(e),
            )

    def get_next_run_time(self, schedule_id: str) -> datetime | None:
        """Get the next scheduled run time for a job.

        Parameters
        ----------
        schedule_id:
            The ID of the schedule.

        Returns
        -------
        datetime | None
            The next run time, or None if the job doesn't exist.
        """
        job = self._scheduler.get_job(schedule_id)
        return job.next_run_time if job else None
