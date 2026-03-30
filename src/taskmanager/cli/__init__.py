"""Taskmanager CLI — Typer-based unified entry point."""

import typer

from taskmanager.cli.serve import serve
from taskmanager.cli.show_settings import show_settings


app = typer.Typer(help="Simplistic task management, for Vibe playground.")
app.command()(serve)
app.command(name="show-settings")(show_settings)


def main() -> None:
    """Entry point for the ``taskmanager`` console script."""
    app()
