"""Task management CLI commands.

This module provides the task sub-command with CRUD operations for tasks.
"""

from typing import Annotated

import typer
from rich.console import Console

from taskmanager.cli.formatters import format_task_table
from taskmanager.database import get_db
from taskmanager.exceptions import DuplicateTaskError, TaskNotFoundError
from taskmanager.executor import execute_task
from taskmanager.services.task_service import (
    create_task,
    delete_task,
    get_task_by_name,
    list_tasks,
    update_task,
)


app = typer.Typer(help="Manage tasks — add, list, show, edit, remove.")
console = Console()
console_err = Console(stderr=True)


@app.command()
def add(
    name: Annotated[str, typer.Option("--name", help="Unique task name")],
    command: Annotated[str, typer.Option("--command", help="Shell command to execute")],
    description: Annotated[
        str | None,
        typer.Option("--description", help="Optional task description"),
    ] = None,
    shell: Annotated[
        str,
        typer.Option("--shell", help="Shell to use for execution"),
    ] = "/bin/sh",
) -> None:
    """Add a new task to the registry."""
    try:
        with get_db() as session:
            task = create_task(
                session=session,
                name=name,
                command=command,
                description=description,
                shell=shell,
            )
            console.print(
                f"[green]✓[/green] Task '{task.name}' created (ID: {task.id})"
            )
    except DuplicateTaskError as e:
        console_err.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(code=1) from None


@app.command(name="list")
def list_command() -> None:
    """List all registered tasks."""
    with get_db() as session:
        tasks = list_tasks(session)

        if not tasks:
            console.print("[yellow]No tasks found.[/yellow]")
            return

        table = format_task_table(tasks, no_color=False)
        if table is not None:
            console.print(table)


@app.command()
def show(
    name: Annotated[str, typer.Argument(help="Task name to display")],
) -> None:
    """Show full details of a task."""
    try:
        with get_db() as session:
            task = get_task_by_name(session, name)

            if task is None:
                console_err.print(f"[red]Error:[/red] Task '{name}' not found")
                raise typer.Exit(code=1) from None

            # Access all attributes INSIDE the session context to avoid DetachedInstanceError
            console.print(f"\n[bold cyan]Task: {task.name}[/bold cyan]")
            console.print(f"[dim]ID:[/dim] {task.id}")
            console.print(f"[dim]Command:[/dim] {task.command}")
            console.print(f"[dim]Shell:[/dim] {task.shell}")
            if task.description:
                console.print(f"[dim]Description:[/dim] {task.description}")
            console.print(
                f"[dim]Created:[/dim] {task.created_at.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            console.print(
                f"[dim]Updated:[/dim] {task.updated_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
            )
    except Exception as e:
        console_err.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1) from None


@app.command()
def edit(
    name: Annotated[str, typer.Argument(help="Task name to edit")],
    new_name: Annotated[
        str | None,
        typer.Option("--name", help="New task name"),
    ] = None,
    command: Annotated[
        str | None,
        typer.Option("--command", help="New command"),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option("--description", help="New description"),
    ] = None,
    shell: Annotated[
        str | None,
        typer.Option("--shell", help="New shell"),
    ] = None,
) -> None:
    """Edit an existing task (partial updates supported)."""
    try:
        with get_db() as session:
            task = get_task_by_name(session, name)

            if task is None:
                console_err.print(f"[red]Error:[/red] Task '{name}' not found")
                raise typer.Exit(code=1) from None

            # Build updates dict
            updates = {}
            if new_name is not None:
                updates["name"] = new_name
            if command is not None:
                updates["command"] = command
            if description is not None:
                updates["description"] = description
            if shell is not None:
                updates["shell"] = shell

            if not updates:
                console.print(
                    "[yellow]No updates provided. Use --name, --command, --description, or --shell.[/yellow]"
                )
                return

            updated_task = update_task(session, task.id, **updates)
            # Access name attribute inside session context to avoid DetachedInstanceError
            task_name = updated_task.name

        # Print success message after session closes
        console.print(f"[green]✓[/green] Task '{task_name}' updated")

    except DuplicateTaskError as e:
        console_err.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(code=1) from None
    except TaskNotFoundError as e:
        console_err.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(code=1) from None


@app.command()
def remove(
    name: Annotated[str, typer.Argument(help="Task name to remove")],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt"),
    ] = False,
) -> None:
    """Remove a task from the registry."""
    try:
        with get_db() as session:
            task = get_task_by_name(session, name)

            if task is None:
                console_err.print(f"[red]Error:[/red] Task '{name}' not found")
                raise typer.Exit(code=1) from None

            # Confirmation prompt unless --yes was provided
            if not yes:
                confirmed = typer.confirm(
                    f"Are you sure you want to remove task '{name}'?"
                )
                if not confirmed:
                    console.print("[yellow]Cancelled.[/yellow]")
                    raise typer.Exit(code=0)

            delete_task(session, task.id)
            console.print(f"[green]✓[/green] Task '{name}' removed")

    except TaskNotFoundError as e:
        console_err.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(code=1) from None


@app.command()
def exec(
    name: Annotated[str, typer.Argument(help="Task name to execute")],
) -> None:
    """Execute a task by name."""
    try:
        with get_db() as session:
            task = get_task_by_name(session, name)

            if task is None:
                console_err.print(f"[red]Error:[/red] Task '{name}' not found")
                raise typer.Exit(code=1) from None

            # Execute the task
            run = execute_task(task, session)

            # Access attributes inside session context to avoid DetachedInstanceError
            run_id_short = run.id[:8]
            status = run.status
            exit_code = run.exit_code or 1

        # Print result after session closes
        if status.value == "success":
            console.print(
                f"[green]✓[/green] Run {run_id_short} completed successfully"
            )
            raise typer.Exit(code=0)

        console.print(f"[red]✗[/red] Run {run_id_short} failed")
        raise typer.Exit(code=exit_code)

    except TaskNotFoundError as e:
        console_err.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(code=1) from None
