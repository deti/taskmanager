"""History management CLI commands.

This module provides the history sub-command with operations for pruning
old run records and viewing execution statistics.
"""

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from taskmanager.cli.formatters import format_duration
from taskmanager.database import get_db
from taskmanager.exceptions import TaskNotFoundError
from taskmanager.services import history_service
from taskmanager.services.task_service import get_task_by_name


app = typer.Typer(help="History management commands")
console = Console()
console_err = Console(stderr=True)


@app.command()
def prune(
    older_than: Annotated[
        int | None,
        typer.Option("--older-than", help="Days to retain (default from settings)"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show count without deleting"),
    ] = False,
) -> None:
    """Delete old run records based on retention policy."""
    try:
        with get_db() as session:
            count = history_service.prune_runs(
                session=session,
                older_than_days=older_than,
                dry_run=dry_run,
            )

        # Output results
        if dry_run:
            console.print(f"[yellow]Would delete {count} runs[/yellow]")
        else:
            console.print(f"[green]Deleted {count} runs[/green]")

    except Exception as e:
        console_err.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1) from None


@app.command()
def stats(
    task_name: Annotated[
        str | None,
        typer.Option("--task", help="Task name for per-task stats"),
    ] = None,
    no_color: Annotated[
        bool,
        typer.Option("--no-color", help="Disable colored output"),
    ] = False,
) -> None:
    """Show execution statistics for runs."""
    try:
        with get_db() as session:
            # Resolve task name to task_id if provided
            task_id = None
            if task_name is not None:
                task_obj = get_task_by_name(session, task_name)
                if task_obj is None:
                    console_err.print(f"[red]Error:[/red] Task '{task_name}' not found")
                    raise typer.Exit(code=1) from None
                task_id = task_obj.id

            # Get statistics
            stats_data = history_service.get_stats(session, task_id)

        # Display main stats table
        stats_table = Table(title="Execution Statistics")
        stats_table.add_column("Metric", style="cyan" if not no_color else None)
        stats_table.add_column("Value", justify="right")

        stats_table.add_row("Total Runs", str(stats_data["total_runs"]))
        stats_table.add_row("Success Rate", f"{stats_data['success_rate']:.1f}%")

        # Handle avg_duration_ms (can be None)
        avg_duration = stats_data.get("avg_duration_ms")
        avg_duration_int = int(avg_duration) if avg_duration is not None else None
        stats_table.add_row("Avg Duration", format_duration(avg_duration_int))

        console.print(stats_table)

        # Display top failed tasks (only for global stats)
        most_failed = stats_data.get("most_failed_tasks", [])
        if most_failed:
            console.print()  # Blank line
            failed_table = Table(title="Top Failed Tasks")
            failed_table.add_column("Task Name", style="magenta" if not no_color else None)
            failed_table.add_column("Failures", justify="right", style="red" if not no_color else None)

            for item in most_failed:
                failed_table.add_row(
                    item["task_name"],
                    str(item["failure_count"]),
                )

            console.print(failed_table)

    except TaskNotFoundError as e:
        console_err.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(code=1) from None
    except Exception as e:
        console_err.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1) from None
