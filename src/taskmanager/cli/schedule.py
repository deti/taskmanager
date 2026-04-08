"""Schedule management CLI commands.

This module provides the schedule sub-command with CRUD operations for task schedules.
Schedules define when and how often tasks should be executed automatically.
"""

import json
import re
from typing import Annotated

import typer
from rich.console import Console
from sqlalchemy import select
from sqlalchemy.orm import Session

from taskmanager.cli.formatters import format_relative_time, format_schedule_table
from taskmanager.database import get_db
from taskmanager.exceptions import (
    DuplicateScheduleError,
    ScheduleNotFoundError,
    ScheduleValidationError,
    TaskNotFoundError,
)
from taskmanager.models import Schedule, Task, TriggerType
from taskmanager.services.schedule_service import (
    create_schedule,
    delete_schedule,
    get_schedule,
    list_schedules,
    update_schedule,
)
from taskmanager.services.task_service import get_task_by_name


app = typer.Typer(help="Manage task schedules — add, list, show, enable, disable, remove.")
console = Console()
console_err = Console(stderr=True)


def _get_schedule_by_id_or_short(session: Session, schedule_id: str) -> Schedule:
    """Get a schedule by full UUID or short ID (first 8 chars).

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    schedule_id:
        Full UUID or first 8 characters of the UUID.

    Returns
    -------
    Schedule
        The retrieved Schedule object.

    Raises
    ------
    ScheduleNotFoundError
        If no schedule with the given ID exists.
    """
    # First try exact match
    try:
        return get_schedule(session, schedule_id)
    except ScheduleNotFoundError:
        pass

    # If it's a short ID (8 chars), try to find a match
    if len(schedule_id) == 8:
        stmt = select(Schedule).where(Schedule.id.startswith(schedule_id))
        result = session.execute(stmt)
        schedules = list(result.scalars().all())

        if len(schedules) == 1:
            return schedules[0]
        if len(schedules) > 1:
            # Multiple matches - ambiguous short ID
            raise ScheduleNotFoundError(schedule_id)

    # Not found
    raise ScheduleNotFoundError(schedule_id)


def _parse_interval_shorthand(interval: str) -> dict[str, dict[str, int]]:
    """Parse interval shorthand like '30m', '1h', '5s' to trigger config.

    Parameters
    ----------
    interval:
        Interval string (e.g., "30m", "1h", "5s", "2d").

    Returns
    -------
    dict
        Trigger config dict with interval specification.

    Raises
    ------
    ScheduleValidationError
        If the interval format is invalid.
    """
    pattern = r"^(\d+)([smhd])$"
    match = re.match(pattern, interval)

    if not match:
        msg = f"Invalid interval format: '{interval}' (expected format: <number><unit>, e.g., '30m', '1h', '5s', '2d')"
        raise ScheduleValidationError(msg)

    value = int(match.group(1))
    unit = match.group(2)

    # Map unit to full name
    unit_map = {
        "s": "seconds",
        "m": "minutes",
        "h": "hours",
        "d": "days",
    }

    return {"interval": {unit_map[unit]: value}}


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


@app.command()
def add(
    task: Annotated[str, typer.Option("--task", help="Task name to schedule")],
    cron: Annotated[str | None, typer.Option("--cron", help="Cron expression (e.g., '0 * * * *')")] = None,
    every: Annotated[str | None, typer.Option("--every", help="Interval shorthand (e.g., '30m', '1h', '5s')")] = None,
    once: Annotated[str | None, typer.Option("--once", help="ISO-8601 datetime for one-time execution")] = None,
    enabled: Annotated[bool, typer.Option("--enabled/--disabled", help="Initial enabled state")] = True,
) -> None:
    """Add a new schedule for a task."""
    # Validate mutual exclusivity
    trigger_count = sum([cron is not None, every is not None, once is not None])
    if trigger_count == 0:
        console_err.print("[red]Error:[/red] Must specify exactly one of --cron, --every, or --once")
        raise typer.Exit(code=1)
    if trigger_count > 1:
        console_err.print("[red]Error:[/red] Cannot specify multiple trigger types (--cron, --every, --once)")
        raise typer.Exit(code=1)

    try:
        with get_db() as session:
            # Look up task by name
            task_obj = get_task_by_name(session, task)
            if task_obj is None:
                console_err.print(f"[red]Error:[/red] Task '{task}' not found")
                raise typer.Exit(code=1)

            # Determine trigger type and build config
            trigger_config: dict[str, str] | dict[str, dict[str, int]]
            if cron is not None:
                trigger_type = TriggerType.CRON
                trigger_config = {"cron": cron}
            elif every is not None:
                trigger_type = TriggerType.INTERVAL
                trigger_config = _parse_interval_shorthand(every)
            else:  # once is not None
                trigger_type = TriggerType.ONCE
                trigger_config = {"once": once if once is not None else ""}

            # Create schedule
            schedule = create_schedule(
                session=session,
                task_id=task_obj.id,
                trigger_type=trigger_type,
                trigger_config=trigger_config,
                enabled=enabled,
            )

            # Access schedule ID inside session to avoid DetachedInstanceError
            schedule_id_short = schedule.id[:8]

        console.print(f"[green]✓[/green] Schedule created (ID: {schedule_id_short})")

    except TaskNotFoundError as e:
        console_err.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(code=1) from None
    except DuplicateScheduleError as e:
        console_err.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(code=1) from None
    except ScheduleValidationError as e:
        console_err.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(code=1) from None


@app.command(name="list")
def list_command(
    task: Annotated[str | None, typer.Option("--task", help="Filter by task name")] = None,
    enabled: Annotated[bool | None, typer.Option("--enabled/--disabled", help="Filter by enabled status")] = None,
    no_color: Annotated[
        bool,
        typer.Option("--no-color", help="Disable colored output"),
    ] = False,
) -> None:
    """List all schedules."""
    with get_db() as session:
        # If task filter provided, look up task ID
        task_id = None
        if task is not None:
            task_obj = get_task_by_name(session, task)
            if task_obj is None:
                console_err.print(f"[red]Error:[/red] Task '{task}' not found")
                raise typer.Exit(code=1)
            task_id = task_obj.id

        # List schedules
        schedules = list_schedules(session, task_id=task_id, enabled=enabled)

        if not schedules:
            console.print("[yellow]No schedules found.[/yellow]")
            return

        table = format_schedule_table(schedules, session, no_color=no_color)
        if table is not None:
            console.print(table)


@app.command()
def show(
    id: Annotated[str, typer.Argument(help="Schedule ID (full or short)")],
) -> None:
    """Show full details of a schedule."""
    try:
        with get_db() as session:
            schedule = _get_schedule_by_id_or_short(session, id)

            # Look up task name
            task_stmt = select(Task).where(Task.id == schedule.task_id)
            task_result = session.execute(task_stmt)
            task_obj = task_result.scalar_one_or_none()
            task_name = task_obj.name if task_obj else "?"

            # Parse trigger config
            trigger_config = json.loads(schedule.trigger_config)

            # Access all attributes inside session context
            schedule_id = schedule.id
            trigger_type = schedule.trigger_type.value
            enabled = schedule.enabled
            next_run_at = schedule.next_run_at
            last_run_at = schedule.last_run_at
            created_at = schedule.created_at
            updated_at = schedule.updated_at

        # Print formatted details after session closes
        console.print(f"\n[bold cyan]Schedule: {schedule_id[:8]}[/bold cyan]")
        console.print(f"[dim]ID:[/dim] {schedule_id}")
        console.print(f"[dim]Task Name:[/dim] {task_name}")
        console.print(f"[dim]Trigger Type:[/dim] {trigger_type}")
        console.print(f"[dim]Trigger Config:[/dim] {json.dumps(trigger_config, indent=2)}")
        console.print(f"[dim]Enabled:[/dim] {'Yes' if enabled else 'No'}")
        console.print(f"[dim]Next Run:[/dim] {format_relative_time(next_run_at)}")
        console.print(f"[dim]Last Run:[/dim] {format_relative_time(last_run_at)}")
        console.print(f"[dim]Created:[/dim] {format_relative_time(created_at)}")
        console.print(f"[dim]Updated:[/dim] {format_relative_time(updated_at)}\n")

    except ScheduleNotFoundError as e:
        console_err.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(code=1) from None


@app.command()
def enable(
    id: Annotated[str, typer.Argument(help="Schedule ID (full or short)")],
) -> None:
    """Enable a schedule."""
    try:
        with get_db() as session:
            schedule = _get_schedule_by_id_or_short(session, id)
            update_schedule(session, schedule.id, enabled=True)
            schedule_id_short = schedule.id[:8]

        console.print(f"[green]✓[/green] Schedule {schedule_id_short} enabled")

    except ScheduleNotFoundError as e:
        console_err.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(code=1) from None


@app.command()
def disable(
    id: Annotated[str, typer.Argument(help="Schedule ID (full or short)")],
) -> None:
    """Disable a schedule."""
    try:
        with get_db() as session:
            schedule = _get_schedule_by_id_or_short(session, id)
            update_schedule(session, schedule.id, enabled=False)
            schedule_id_short = schedule.id[:8]

        console.print(f"[green]✓[/green] Schedule {schedule_id_short} disabled")

    except ScheduleNotFoundError as e:
        console_err.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(code=1) from None


@app.command()
def remove(
    id: Annotated[str, typer.Argument(help="Schedule ID (full or short)")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompt")] = False,
) -> None:
    """Remove a schedule."""
    try:
        with get_db() as session:
            schedule = _get_schedule_by_id_or_short(session, id)
            schedule_id_short = schedule.id[:8]

            # Confirmation prompt unless --yes was provided
            if not yes:
                confirmed = typer.confirm(
                    f"Are you sure you want to remove schedule {schedule_id_short}?"
                )
                if not confirmed:
                    console.print("[yellow]Cancelled.[/yellow]")
                    raise typer.Exit(code=0)

            delete_schedule(session, schedule.id)

        console.print(f"[green]✓[/green] Schedule {schedule_id_short} removed")

    except ScheduleNotFoundError as e:
        console_err.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(code=1) from None
