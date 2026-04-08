"""Plugin hook specifications for the taskmanager plugin system.

This module defines the hook specification interface that plugins can implement
to extend taskmanager functionality at key lifecycle points.
"""

from typing import TYPE_CHECKING, Any

import pluggy


if TYPE_CHECKING:
    from taskmanager.models import Run, Task

hookspec = pluggy.HookspecMarker("taskmanager")


class TaskManagerHookspec:
    """Hook specifications for taskmanager plugins."""

    @hookspec
    def on_task_registered(self, task: "Task") -> None:
        """Called when a new task is created.

        Parameters
        ----------
        task:
            The newly created Task object.
        """

    @hookspec
    def on_before_execute(self, task: "Task", run: "Run") -> bool | None:
        """Called before task execution.

        Plugins can return False to veto execution. If any plugin returns False,
        the task will not execute.

        Parameters
        ----------
        task:
            The Task object about to be executed.
        run:
            The Run object representing this execution attempt.

        Returns
        -------
        bool | None
            False to prevent execution, True or None to allow it.
        """

    @hookspec
    def on_after_execute(self, task: "Task", run: "Run") -> None:
        """Called after task execution completes.

        Parameters
        ----------
        task:
            The Task object that was executed.
        run:
            The completed Run object with execution results.
        """

    @hookspec
    def register_commands(self, app: Any) -> None:
        """Called to register custom CLI commands.

        Parameters
        ----------
        app:
            The Typer app instance to register commands with.
        """

    @hookspec
    def register_api_routes(self, router: Any) -> None:
        """Called to register custom API routes.

        Parameters
        ----------
        router:
            The FastAPI APIRouter instance to register routes with.
        """
