"""Taskmanager CLI — Typer-based unified entry point."""

import typer

from taskmanager.cli.config import app as config_app
from taskmanager.cli.data import app as data_app
from taskmanager.cli.history import app as history_app
from taskmanager.cli.hook import app as hook_app
from taskmanager.cli.plugin import app as plugin_app
from taskmanager.cli.run import app as run_app
from taskmanager.cli.schedule import app as schedule_app
from taskmanager.cli.serve import serve
from taskmanager.cli.show_settings import show_settings
from taskmanager.cli.task import app as task_app
from taskmanager.plugins import PluginManager


app = typer.Typer(help="Simplistic task management, for Vibe playground.")

# Initialize plugin manager and let plugins register commands
pm = PluginManager()
pm.call_register_commands(app)

app.command()(serve)
app.command(name="show-settings")(show_settings)
app.add_typer(task_app, name="task")
app.add_typer(run_app, name="run")
app.add_typer(config_app, name="config")
app.add_typer(schedule_app, name="schedule")
app.add_typer(hook_app, name="hook")
app.add_typer(plugin_app, name="plugin")
app.add_typer(history_app, name="history")
app.add_typer(data_app, name="data")


def main() -> None:
    """Entry point for the ``taskmanager`` console script."""
    app()
