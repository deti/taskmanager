"""Plugin management CLI commands.

This module provides the plugin sub-command for listing and inspecting plugins.
"""

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from taskmanager.plugins import PluginManager


app = typer.Typer(help="Manage plugins — list and show plugin information.")
console = Console()
console_err = Console(stderr=True)


@app.command(name="list")
def list_command() -> None:
    """List all discovered plugins."""
    pm = PluginManager()
    plugins = pm.list_plugins()

    if not plugins:
        console.print("[yellow]No plugins installed[/yellow]")
        return

    table = Table(title="Installed Plugins")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Version", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Error", style="red")

    for plugin in plugins:
        error_display = plugin["error"] if plugin["error"] else ""
        status_style = "green" if plugin["status"] == "loaded" else "red"
        status_display = f"[{status_style}]{plugin['status']}[/{status_style}]"

        table.add_row(
            plugin["name"],
            plugin["version"],
            status_display,
            error_display,
        )

    console.print(table)


@app.command()
def info(
    name: Annotated[str, typer.Argument(help="Plugin name to display")],
) -> None:
    """Show detailed information about a plugin."""
    pm = PluginManager()
    plugins = pm.list_plugins()

    # Find plugin by name
    plugin = next((p for p in plugins if p["name"] == name), None)

    if plugin is None:
        console_err.print(f"[red]Error:[/red] Plugin '{name}' not found")
        raise typer.Exit(code=1)

    # Display plugin details
    console.print(f"\n[bold cyan]Plugin: {plugin['name']}[/bold cyan]")
    console.print(f"[dim]Version:[/dim] {plugin['version']}")
    console.print(f"[dim]Module:[/dim] {plugin['module']}")

    status_style = "green" if plugin["status"] == "loaded" else "red"
    console.print(f"[dim]Status:[/dim] [{status_style}]{plugin['status']}[/{status_style}]")

    if plugin["error"]:
        console.print(f"[dim]Error:[/dim] [red]{plugin['error']}[/red]")

    console.print()
