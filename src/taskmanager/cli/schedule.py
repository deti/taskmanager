"""Schedule management CLI commands.

This module provides the schedule sub-command with CRUD operations for task schedules.
Schedules define when and how often tasks should be executed automatically.
"""

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from taskmanager.database import get_db
from taskmanager.exceptions import (
    DuplicateScheduleError,
    ScheduleNotFoundError,
    ScheduleValidationError,
    TaskNotFoundError,
)
from taskmanager.models import TriggerType
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
