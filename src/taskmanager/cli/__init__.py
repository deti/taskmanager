"""Taskmanager CLI — Typer-based unified entry point."""

import typer

from taskmanager.cli.run import app as run_app
from taskmanager.cli.serve import serve
from taskmanager.cli.show_settings import show_settings
from taskmanager.cli.task import app as task_app


app = typer.Typer(help="Simplistic task management, for Vibe playground.")
app.command()(serve)
app.command(name="show-settings")(show_settings)
app.add_typer(task_app, name="task")
app.add_typer(run_app, name="run")


def main() -> None:
    """Entry point for the ``taskmanager`` console script."""
    app()
