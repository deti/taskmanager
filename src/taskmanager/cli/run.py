"""Run management CLI commands.

This module provides the run sub-command with operations for viewing
task execution runs, their status, and logs.
"""

from typing import Annotated

import typer
from rich.console import Console
from sqlalchemy import select
from sqlalchemy.orm import Session

from taskmanager.cli.formatters import format_duration, format_relative_time, format_run_table
from taskmanager.database import get_db
from taskmanager.exceptions import RunNotFoundError, TaskNotFoundError
from taskmanager.executor import execute_inline
from taskmanager.models import Run, RunStatus, Task
from taskmanager.services.run_service import get_run, list_runs
from taskmanager.services.task_service import get_task_by_name


app = typer.Typer(help="View task execution runs, status, and logs.")
console = Console()
console_err = Console(stderr=True)


def _get_run_by_id_or_short(session: Session, run_id: str) -> Run:
    """Get a run by full UUID or short ID (first 8 chars).

    Parameters
    ----------
    session:
        SQLAlchemy session for database operations.
    run_id:
        Full UUID or first 8 characters of the UUID.

    Returns
    -------
    Run
        The retrieved Run object.

    Raises
    ------
    RunNotFoundError
        If no run with the given ID exists.
    """
    # First try exact match
    try:
        return get_run(session, run_id)
    except RunNotFoundError:
        pass

    # If it's a short ID (8 chars), try to find a match
    if len(run_id) == 8:
        stmt = select(Run).where(Run.id.startswith(run_id))
        result = session.execute(stmt)
        runs = list(result.scalars().all())

        if len(runs) == 1:
            return runs[0]
        if len(runs) > 1:
            # Multiple matches - ambiguous short ID
            raise RunNotFoundError(run_id)

    # Not found
    raise RunNotFoundError(run_id)


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


@app.command()
def exec(
    command: Annotated[str, typer.Argument(help="Command to execute")],
) -> None:
    """Execute a command inline and show results immediately."""
    try:
        with get_db() as session:
            # Execute the command
            run = execute_inline(command, session)

            # Access attributes inside session context
            run_id = run.id
            exit_code = run.exit_code or 0
            stdout = run.stdout or ""
            stderr = run.stderr or ""

    except Exception as e:
        console_err.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1) from None

    # Print output after session closes
    console.print("\n[bold cyan]STDOUT:[/bold cyan]")
    if stdout.strip():
        console.print(stdout)
    else:
        console.print("[dim](empty)[/dim]")

    console.print("\n[bold cyan]STDERR:[/bold cyan]")
    if stderr.strip():
        console.print(stderr)
    else:
        console.print("[dim](empty)[/dim]")

    # Print status footer
    console.print(f"\n[dim]Run ID: {run_id[:8]}[/dim]")

    # Print success/failure message with exit code
    if exit_code == 0:
        console.print(f"[green]✓[/green] Command completed successfully (exit code: {exit_code})")
    else:
        console.print(f"[red]✗[/red] Command failed (exit code: {exit_code})")

    # Exit with the command's exit code
    raise typer.Exit(code=exit_code)


@app.command(name="list")
def list_command(
    task: Annotated[
        str | None,
        typer.Option("--task", help="Filter by task name"),
    ] = None,
    status: Annotated[
        str | None,
        typer.Option("--status", help="Filter by status (pending/running/success/failed/cancelled)"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", help="Maximum number of runs to display"),
    ] = 20,
) -> None:
    """List task execution runs."""
    try:
        with get_db() as session:
            # Build filters
            task_id = None
            if task is not None:
                task_obj = get_task_by_name(session, task)
                if task_obj is None:
                    console_err.print(f"[red]Error:[/red] Task '{task}' not found")
                    raise typer.Exit(code=1) from None
                task_id = task_obj.id

            status_enum = None
            if status is not None:
                try:
                    status_enum = RunStatus(status.lower())
                except ValueError:
                    console_err.print(
                        f"[red]Error:[/red] Invalid status '{status}'. "
                        f"Valid values: pending, running, success, failed, cancelled"
                    )
                    raise typer.Exit(code=1) from None

            # Get runs
            runs = list_runs(
                session=session,
                task_id=task_id,
                status=status_enum,
                limit=limit,
            )

            if not runs:
                console.print("[yellow]No runs found.[/yellow]")
                return

            table = format_run_table(runs, session, no_color=False)
            if table is not None:
                console.print(table)

    except TaskNotFoundError as e:
        console_err.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(code=1) from None


@app.command()
def show(
    run_id: Annotated[str, typer.Argument(help="Run ID (full UUID or first 8 chars)")],
) -> None:
    """Show detailed information about a run."""
    try:
        with get_db() as session:
            run = _get_run_by_id_or_short(session, run_id)

            # Get task name
            if run.task_id is None:
                task_name = "(inline)"
            else:
                task_stmt = select(Task).where(Task.id == run.task_id)
                task_result = session.execute(task_stmt)
                task_obj = task_result.scalar_one_or_none()
                task_name = task_obj.name if task_obj else "(unknown)"

            # Access all attributes inside session context
            run_id_full = run.id
            status = run.status.value
            command = run.command_snapshot
            exit_code = run.exit_code
            duration_ms = run.duration_ms
            started_at = run.started_at
            finished_at = run.finished_at
            error_message = run.error_message

        # Print details after session closes
        console.print(f"\n[bold cyan]Run: {run_id_full}[/bold cyan]")
        console.print(f"[dim]Task:[/dim] {task_name}")
        console.print(f"[dim]Status:[/dim] [{_status_color(RunStatus(status))}]{status}[/{_status_color(RunStatus(status))}]")
        console.print(f"[dim]Command:[/dim] {command}")

        if exit_code is not None:
            console.print(f"[dim]Exit Code:[/dim] {exit_code}")

        console.print(f"[dim]Duration:[/dim] {format_duration(duration_ms)}")
        console.print(f"[dim]Started At:[/dim] {format_relative_time(started_at)}")
        console.print(f"[dim]Finished At:[/dim] {format_relative_time(finished_at)}")

        if error_message:
            console.print(f"[dim]Error:[/dim] [red]{error_message}[/red]")

        console.print()

    except RunNotFoundError as e:
        console_err.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(code=1) from None


@app.command()
def logs(
    run_id: Annotated[str, typer.Argument(help="Run ID (full UUID or first 8 chars)")],
) -> None:
    """Show stdout and stderr for a run."""
    try:
        with get_db() as session:
            run = _get_run_by_id_or_short(session, run_id)

            # Access attributes inside session context
            stdout = run.stdout
            stderr = run.stderr

        # Print logs after session closes
        console.print("\n[bold cyan]=== STDOUT ===[/bold cyan]")
        if stdout:
            console.print(stdout)
        else:
            console.print("[dim](empty)[/dim]")

        console.print("\n[bold cyan]=== STDERR ===[/bold cyan]")
        if stderr:
            console.print(stderr)
        else:
            console.print("[dim](empty)[/dim]")

        console.print()

    except RunNotFoundError as e:
        console_err.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(code=1) from None
