"""Data export and import CLI commands.

This module provides commands for exporting and importing tasks, schedules,
and hooks to/from YAML files for backup and portability.
"""

from pathlib import Path
from typing import Annotated

import typer
import yaml  # type: ignore[import-untyped]
from rich.console import Console
from rich.table import Table

from taskmanager.database import get_db
from taskmanager.services import export_service


app = typer.Typer(help="Export and import tasks, schedules, and hooks as YAML.")
console = Console()
console_err = Console(stderr=True)


@app.command()
def export(
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Path to write YAML export file."),
    ],
) -> None:
    """Export all tasks, schedules, and hooks to a YAML file.

    Creates a complete backup that can be restored with 'data import'.
    The YAML format is human-readable and version-control friendly.
    """
    try:
        with get_db() as session:
            data = export_service.export_all(session)

        # Write YAML to file
        with output.open("w") as f:
            yaml.safe_dump(
                data,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )

        # Count entities
        task_count = len(data.get("tasks", []))
        schedule_count = len(data.get("schedules", []))
        hook_count = len(data.get("hooks", []))

        console.print(
            f"[green]Exported {task_count} tasks, "
            f"{schedule_count} schedules, {hook_count} hooks to {output}[/green]"
        )

    except PermissionError:
        console_err.print(f"[red]Error:[/red] Permission denied: {output}")
        raise typer.Exit(code=1) from None
    except OSError as e:
        console_err.print(f"[red]Error:[/red] Failed to write file: {e}")
        raise typer.Exit(code=1) from None
    except Exception as e:
        console_err.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1) from None


@app.command(name="import")
def import_data(
    input_file: Annotated[
        Path,
        typer.Option("--input", "-i", help="Path to YAML file to import."),
    ],
    on_conflict: Annotated[
        str,
        typer.Option(
            "--on-conflict",
            help="How to handle existing records: skip, overwrite, or error (default: error).",
        ),
    ] = "error",
) -> None:
    """Import tasks, schedules, and hooks from a YAML file.

    Restores data exported with 'data export'. By default, errors on conflicts.
    Use --on-conflict=skip to ignore existing records or --on-conflict=overwrite
    to replace them.
    """
    # Validate on_conflict value
    if on_conflict not in ("skip", "overwrite", "error"):
        console_err.print(
            "[red]Error:[/red] Invalid --on-conflict value. "
            "Must be 'skip', 'overwrite', or 'error'"
        )
        raise typer.Exit(code=1)

    try:
        # Read and parse YAML file
        with input_file.open() as f:
            data = yaml.safe_load(f)

        if data is None:
            console_err.print("[red]Error:[/red] YAML file is empty")
            raise typer.Exit(code=1)

        # Import data
        with get_db() as session:
            stats = export_service.import_all(
                session,
                data,
                on_conflict=on_conflict,  # type: ignore[arg-type]
            )

        # Display import summary table
        summary_table = Table(title="Import Summary")
        summary_table.add_column("Entity", style="cyan")
        summary_table.add_column("Created", justify="right", style="green")
        summary_table.add_column("Updated", justify="right", style="yellow")
        summary_table.add_column("Skipped", justify="right", style="blue")

        summary_table.add_row(
            "Tasks",
            str(stats["tasks_created"]),
            str(stats["tasks_updated"]),
            str(stats["tasks_skipped"]),
        )
        summary_table.add_row(
            "Schedules",
            str(stats["schedules_created"]),
            str(stats["schedules_updated"]),
            str(stats["schedules_skipped"]),
        )
        summary_table.add_row(
            "Hooks",
            str(stats["hooks_created"]),
            str(stats["hooks_updated"]),
            str(stats["hooks_skipped"]),
        )

        console.print(summary_table)

        # Print success message
        total_created = (
            stats["tasks_created"] + stats["schedules_created"] + stats["hooks_created"]
        )
        total_updated = (
            stats["tasks_updated"] + stats["schedules_updated"] + stats["hooks_updated"]
        )
        total_skipped = (
            stats["tasks_skipped"] + stats["schedules_skipped"] + stats["hooks_skipped"]
        )

        console.print(
            f"\n[green]Import complete:[/green] "
            f"{total_created} created, {total_updated} updated, {total_skipped} skipped"
        )

    except FileNotFoundError:
        console_err.print(f"[red]Error:[/red] File not found: {input_file}")
        raise typer.Exit(code=1) from None
    except yaml.YAMLError as e:
        console_err.print(f"[red]Error:[/red] Invalid YAML format: {e}")
        raise typer.Exit(code=1) from None
    except (TypeError, ValueError) as e:
        console_err.print(f"[red]Error:[/red] Invalid data structure: {e}")
        raise typer.Exit(code=1) from None
    except Exception as e:
        console_err.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1) from None
