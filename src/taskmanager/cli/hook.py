"""Hook management CLI commands.

This module provides the hook sub-command with CRUD operations for hooks.
"""

import json
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from taskmanager.database import get_db
from taskmanager.exceptions import (
    DuplicateHookError,
    HookNotFoundError,
    HookValidationError,
)
from taskmanager.models import ActionType
from taskmanager.services.hook_service import (
    create_hook,
    delete_hook,
    disable_hook,
    enable_hook,
    get_hook_by_name,
    list_hooks,
)


app = typer.Typer(help="Manage hooks — add, list, show, enable, disable, remove.")
console = Console()
console_err = Console(stderr=True)


@app.command()
def add(
    name: Annotated[str, typer.Option("--name", help="Unique hook name")],
    on: Annotated[str, typer.Option("--on", help="Event type to listen for")],
    action: Annotated[
        str,
        typer.Option(
            "--action",
            help="Action type: shell, webhook, or log",
        ),
    ],
    command: Annotated[
        str | None,
        typer.Option("--command", help="Shell command (required for shell action)"),
    ] = None,
    url: Annotated[
        str | None,
        typer.Option("--url", help="Webhook URL (required for webhook action)"),
    ] = None,
    task: Annotated[
        str | None,
        typer.Option("--task", help="Optional task ID to filter events"),
    ] = None,
) -> None:
    """Add a new hook to execute actions on events."""
    # Normalize action type
    action_lower = action.lower()

    # Map to ActionType enum
    action_type_map = {
        "shell": ActionType.SHELL,
        "webhook": ActionType.WEBHOOK,
        "log": ActionType.LOG,
    }

    if action_lower not in action_type_map:
        console_err.print(
            f"[red]Error:[/red] Invalid action type '{action}'. Must be one of: shell, webhook, log"
        )
        raise typer.Exit(code=1)

    action_type = action_type_map[action_lower]

    # Build action_config based on action type
    action_config_dict: dict[str, str] = {}

    if action_type == ActionType.SHELL:
        if command is None:
            console_err.print(
                "[red]Error:[/red] --command is required for shell action"
            )
            raise typer.Exit(code=1)
        action_config_dict["command"] = command

    elif action_type == ActionType.WEBHOOK:
        if url is None:
            console_err.print("[red]Error:[/red] --url is required for webhook action")
            raise typer.Exit(code=1)
        action_config_dict["url"] = url

    elif action_type == ActionType.LOG:
        # LOG action is flexible — default to empty config
        pass

    # Serialize action_config to JSON
    action_config = json.dumps(action_config_dict)

    try:
        with get_db() as session:
            hook = create_hook(
                session=session,
                name=name,
                event_type=on,
                action_type=action_type,
                action_config=action_config,
                task_filter=task,
            )
            # Access attributes inside session context to avoid DetachedInstanceError
            hook_name = hook.name

        # Print success message after session closes
        console.print(f"[green]✓[/green] Hook '{hook_name}' created")

    except DuplicateHookError as e:
        console_err.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(code=1) from None
    except HookValidationError as e:
        console_err.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(code=1) from None
    except Exception as e:
        console_err.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1) from None


@app.command(name="list")
def list_command(
    disabled: Annotated[
        bool,
        typer.Option("--disabled", help="Show only disabled hooks"),
    ] = False,
) -> None:
    """List all hooks."""
    with get_db() as session:
        # If --disabled flag is set, show only disabled hooks
        if disabled:
            hooks = list_hooks(session, enabled=False)
        else:
            # Show all hooks (both enabled and disabled)
            hooks = list_hooks(session, enabled=None)

        if not hooks:
            console.print("[yellow]No hooks found.[/yellow]")
            return

        table = Table(title="Registered Hooks")
        table.add_column("Name", style="cyan", no_wrap=True)
        table.add_column("Event Type", style="magenta")
        table.add_column("Action", style="yellow")
        table.add_column("Task Filter", style="blue")
        table.add_column("Enabled", style="green")

        for hook in hooks:
            # Access all attributes INSIDE the session context
            task_filter_display = hook.task_filter[:8] if hook.task_filter else "global"
            enabled_display = "✓" if hook.enabled else "✗"
            table.add_row(
                hook.name,
                hook.event_type,
                hook.action_type.value,
                task_filter_display,
                enabled_display,
            )

    console.print(table)


@app.command()
def show(
    name: Annotated[str, typer.Argument(help="Hook name to display")],
) -> None:
    """Show full details of a hook."""
    try:
        with get_db() as session:
            hook = get_hook_by_name(session, name)

            if hook is None:
                console_err.print(f"[red]Error:[/red] Hook '{name}' not found")
                raise typer.Exit(code=1) from None

            # Access all attributes INSIDE the session context
            hook_name = hook.name
            hook_id = hook.id
            event_type = hook.event_type
            action_type = hook.action_type.value
            action_config = hook.action_config
            task_filter = hook.task_filter
            enabled = hook.enabled
            created_at = hook.created_at.strftime("%Y-%m-%d %H:%M:%S")
            updated_at = hook.updated_at.strftime("%Y-%m-%d %H:%M:%S")

        # Print details after session closes
        console.print(f"\n[bold cyan]Hook: {hook_name}[/bold cyan]")
        console.print(f"[dim]ID:[/dim] {hook_id}")
        console.print(f"[dim]Event Type:[/dim] {event_type}")
        console.print(f"[dim]Action Type:[/dim] {action_type}")
        console.print(f"[dim]Enabled:[/dim] {'Yes' if enabled else 'No'}")

        if task_filter:
            console.print(f"[dim]Task Filter:[/dim] {task_filter}")
        else:
            console.print("[dim]Task Filter:[/dim] global")

        # Format action_config JSON with syntax highlighting
        try:
            parsed_config = json.loads(action_config)
            formatted_config = json.dumps(parsed_config, indent=2)
            syntax = Syntax(formatted_config, "json", theme="monokai", line_numbers=False)
            console.print("\n[dim]Action Config:[/dim]")
            console.print(Panel(syntax, expand=False))
        except json.JSONDecodeError:
            console.print(f"[dim]Action Config:[/dim] {action_config}")

        console.print(f"[dim]Created:[/dim] {created_at}")
        console.print(f"[dim]Updated:[/dim] {updated_at}\n")

    except Exception as e:
        console_err.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1) from None


@app.command()
def enable(
    name: Annotated[str, typer.Argument(help="Hook name to enable")],
) -> None:
    """Enable a hook."""
    try:
        with get_db() as session:
            hook = enable_hook(session, name)
            # Access name inside session context
            hook_name = hook.name

        console.print(f"[green]✓[/green] Hook '{hook_name}' enabled")

    except HookNotFoundError as e:
        console_err.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(code=1) from None


@app.command()
def disable(
    name: Annotated[str, typer.Argument(help="Hook name to disable")],
) -> None:
    """Disable a hook."""
    try:
        with get_db() as session:
            hook = disable_hook(session, name)
            # Access name inside session context
            hook_name = hook.name

        console.print(f"[green]✓[/green] Hook '{hook_name}' disabled")

    except HookNotFoundError as e:
        console_err.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(code=1) from None


@app.command()
def remove(
    name: Annotated[str, typer.Argument(help="Hook name to remove")],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt"),
    ] = False,
) -> None:
    """Remove a hook."""
    try:
        with get_db() as session:
            hook = get_hook_by_name(session, name)

            if hook is None:
                console_err.print(f"[red]Error:[/red] Hook '{name}' not found")
                raise typer.Exit(code=1) from None

            # Confirmation prompt unless --yes was provided
            if not yes:
                confirmed = typer.confirm(f"Are you sure you want to remove hook '{name}'?")
                if not confirmed:
                    console.print("[yellow]Cancelled.[/yellow]")
                    raise typer.Exit(code=0)

            delete_hook(session, name)
            console.print(f"[green]✓[/green] Hook '{name}' removed")

    except HookNotFoundError as e:
        console_err.print(f"[red]Error:[/red] {e.message}")
        raise typer.Exit(code=1) from None
