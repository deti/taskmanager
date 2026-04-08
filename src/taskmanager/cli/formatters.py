"""Rich formatting utilities for CLI output.

This module provides reusable table formatters, duration/time formatters,
and console helpers for consistent Rich-formatted output across all CLI commands.
"""

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from taskmanager.models import Run, RunStatus, Schedule, Task, TriggerType


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def get_console(no_color: bool = False) -> Console:
    """Return a Console instance with appropriate settings.

    Parameters
    ----------
    no_color:
        If True, disable all color and styling.

    Returns
    -------
    Console
        Configured Rich Console instance.
    """
    return Console(force_terminal=not no_color, no_color=no_color)


def format_duration(duration_ms: int | None) -> str:
    """Format duration in milliseconds to human-readable string.

    Parameters
    ----------
    duration_ms:
        Duration in milliseconds, or None.

    Returns
    -------
    str
        Formatted duration string (e.g., "1.2s", "45s", "2m 30s") or "-" if None.

    Examples
    --------
    >>> format_duration(1234)
    '1.2s'
    >>> format_duration(45000)
    '45.0s'
    >>> format_duration(150000)
    '2m 30s'
    >>> format_duration(None)
    '-'
    """
    if duration_ms is None:
        return "-"

    seconds = duration_ms / 1000

    # Less than 1 minute: show as seconds
    if seconds < 60:
        return f"{seconds:.1f}s"

    # 1 minute or more: show as minutes and seconds
    minutes = int(seconds // 60)
    remaining_seconds = int(seconds % 60)

    if remaining_seconds == 0:
        return f"{minutes}m"

    return f"{minutes}m {remaining_seconds}s"


def format_relative_time(dt: datetime | None) -> str:  # noqa: PLR0911
    """Convert datetime to relative time string.

    Parameters
    ----------
    dt:
        Datetime object or None.

    Returns
    -------
    str
        Relative time string (e.g., "2 hours ago", "yesterday", "just now")
        or absolute date if >7 days, or "-" if None.

    Examples
    --------
    >>> from datetime import datetime, UTC, timedelta
    >>> now = datetime.now(UTC)
    >>> format_relative_time(now - timedelta(seconds=30))
    'just now'
    >>> format_relative_time(now - timedelta(hours=2))
    '2 hours ago'
    >>> format_relative_time(None)
    '-'
    """
    if dt is None:
        return "-"

    # Ensure timezone-aware comparison
    now = datetime.now(UTC)
    if dt.tzinfo is None:
        # Assume UTC if naive
        dt = dt.replace(tzinfo=UTC)

    delta = now - dt
    total_seconds = delta.total_seconds()

    # Future dates
    if total_seconds < 0:
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    # Less than 1 minute
    if total_seconds < 60:
        return "just now"

    # Less than 1 hour
    if total_seconds < 3600:
        minutes = int(total_seconds // 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"

    # Less than 1 day
    if total_seconds < 86400:
        hours = int(total_seconds // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"

    # Less than 2 days
    if total_seconds < 172800:
        return "yesterday"

    # Less than 7 days
    if total_seconds < 604800:
        days = int(total_seconds // 86400)
        return f"{days} days ago"

    # More than 7 days: show absolute date
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _status_color(status: RunStatus) -> str:
    """Get Rich color for a run status.

    Parameters
    ----------
    status:
        RunStatus enum value.

    Returns
    -------
    str
        Rich color name.
    """
    color_map = {
        RunStatus.SUCCESS: "green",
        RunStatus.FAILED: "red",
        RunStatus.RUNNING: "yellow",
        RunStatus.PENDING: "dim",
        RunStatus.CANCELLED: "dim",
    }
    return color_map.get(status, "white")


def format_task_table(tasks: list[Task], no_color: bool = False) -> Table | None:
    """Format a list of tasks as a Rich table.

    Parameters
    ----------
    tasks:
        List of Task objects to format.
    no_color:
        If True, disable color styling.

    Returns
    -------
    Table | None
        Formatted Rich Table, or None if the list is empty.

    Notes
    -----
    All task attributes must be accessed before the SQLAlchemy session closes
    to avoid DetachedInstanceError.
    """
    if not tasks:
        return None

    table = Table(title="Registered Tasks")
    table.add_column("Name", style="cyan" if not no_color else None, no_wrap=True)
    table.add_column("Command", style="magenta" if not no_color else None)
    table.add_column("Created At", style="green" if not no_color else None)

    for task in tasks:
        # Truncate command if too long
        cmd_display = task.command if len(task.command) <= 50 else task.command[:47] + "..."
        created_at_str = task.created_at.strftime("%Y-%m-%d %H:%M:%S")
        table.add_row(task.name, cmd_display, created_at_str)

    return table


def format_run_table(
    runs: list[Run], session: "Session", no_color: bool = False
) -> Table | None:
    """Format a list of runs as a Rich table.

    Parameters
    ----------
    runs:
        List of Run objects to format.
    session:
        SQLAlchemy session for joining with tasks table.
    no_color:
        If True, disable color styling.

    Returns
    -------
    Table | None
        Formatted Rich Table, or None if the list is empty.

    Notes
    -----
    This function performs database joins to fetch task names.
    All attributes must be accessed before the session closes.
    """
    if not runs:
        return None

    table = Table(title="Task Execution Runs")
    table.add_column("ID", style="cyan" if not no_color else None, no_wrap=True)
    table.add_column("Task", style="magenta" if not no_color else None)
    table.add_column("Status", no_wrap=True)
    table.add_column("Duration", justify="right")
    table.add_column("Started At", style="dim" if not no_color else None)

    for run in runs:
        # Get task name for this run
        if run.task_id is None:
            task_name = "(inline)"
        else:
            task_stmt = select(Task).where(Task.id == run.task_id)
            task_result = session.execute(task_stmt)
            task_obj = task_result.scalar_one_or_none()
            task_name = task_obj.name if task_obj else "(unknown)"

        # Format row data
        run_id_short = run.id[:8]
        status_str = run.status.value
        if no_color:
            status_colored = status_str
        else:
            color = _status_color(run.status)
            status_colored = f"[{color}]{status_str}[/{color}]"
        duration_str = format_duration(run.duration_ms)
        timestamp_str = format_relative_time(run.started_at)

        table.add_row(
            run_id_short,
            task_name,
            status_colored,
            duration_str,
            timestamp_str,
        )

    return table


def _format_trigger(trigger_type: TriggerType, trigger_config_json: str) -> str:  # noqa: PLR0911
    """Format trigger for display in table or show command.

    Parameters
    ----------
    trigger_type:
        The trigger type enum.
    trigger_config_json:
        JSON string of trigger configuration.

    Returns
    -------
    str
        Formatted trigger display string.
    """
    config = json.loads(trigger_config_json)

    if trigger_type == TriggerType.CRON:
        return f"cron: {config.get('cron', '?')}"
    if trigger_type == TriggerType.INTERVAL:
        interval = config.get("interval", {})
        # Format as shorthand if possible
        if "seconds" in interval and len(interval) == 1:
            return f"interval: {interval['seconds']}s"
        if "minutes" in interval and len(interval) == 1:
            return f"interval: {interval['minutes']}m"
        if "hours" in interval and len(interval) == 1:
            return f"interval: {interval['hours']}h"
        if "days" in interval and len(interval) == 1:
            return f"interval: {interval['days']}d"
        # Complex interval, show full dict
        return f"interval: {interval}"
    if trigger_type == TriggerType.ONCE:
        return f"once: {config.get('once', '?')}"
    return "unknown"


def format_schedule_table(
    schedules: list[Schedule], session: "Session", no_color: bool = False
) -> Table | None:
    """Format a list of schedules as a Rich table.

    Parameters
    ----------
    schedules:
        List of Schedule objects to format.
    session:
        SQLAlchemy session for joining with tasks table.
    no_color:
        If True, disable color styling.

    Returns
    -------
    Table | None
        Formatted Rich Table, or None if the list is empty.

    Notes
    -----
    This function performs database joins to fetch task names.
    All attributes must be accessed before the session closes.
    """
    if not schedules:
        return None

    table = Table(title="Task Schedules")
    table.add_column("ID", style="cyan" if not no_color else None, no_wrap=True)
    table.add_column("Task Name", style="magenta" if not no_color else None)
    table.add_column("Trigger", style="blue" if not no_color else None)
    table.add_column("Enabled", style="green" if not no_color else None)
    table.add_column("Next Run", style="yellow" if not no_color else None)
    table.add_column("Last Run", style="dim" if not no_color else None)

    for schedule in schedules:
        # Get task name for this schedule
        task_stmt = select(Task).where(Task.id == schedule.task_id)
        task_result = session.execute(task_stmt)
        task_obj = task_result.scalar_one_or_none()
        task_name = task_obj.name if task_obj else "(unknown)"

        # Format row data
        schedule_id_short = schedule.id[:8]
        trigger_display = _format_trigger(schedule.trigger_type, schedule.trigger_config)
        enabled_display = "✓" if schedule.enabled else "✗"
        next_run_str = format_relative_time(schedule.next_run_at)
        last_run_str = format_relative_time(schedule.last_run_at)

        table.add_row(
            schedule_id_short,
            task_name,
            trigger_display,
            enabled_display,
            next_run_str,
            last_run_str,
        )

    return table
