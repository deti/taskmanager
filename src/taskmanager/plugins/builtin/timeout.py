"""Timeout plugin — overrides subprocess timeout from task metadata.

This plugin implements the on_before_execute hook to override the default
subprocess timeout based on timeout_seconds configuration in task metadata.

Configuration in task.task_metadata:
{
    "timeout_seconds": 30  # Timeout in seconds (overrides settings.subprocess_timeout)
}

Example:
    A task with timeout_seconds=5 will timeout after 5 seconds instead of the
    default 300 seconds configured in settings.

Integration:
    This plugin sets run.timeout_override, which the executor must check before
    calling subprocess.run(). The executor integration is handled by task-service crew.
"""

from typing import TYPE_CHECKING

from pluggy import HookimplMarker

from taskmanager.logging import get_logger


if TYPE_CHECKING:
    from taskmanager.models import Run, Task

logger = get_logger(__name__)
hookimpl = HookimplMarker("taskmanager")


class TimeoutPlugin:
    """Plugin for per-task timeout override."""

    @hookimpl
    def on_before_execute(self, task: "Task", run: "Run") -> bool | None:
        """Override subprocess timeout based on task metadata.

        This hook is called before task execution. If timeout_seconds is configured
        in task.task_metadata, this plugin sets run.timeout_override as a signal
        to the executor to use this timeout instead of the default.

        Parameters
        ----------
        task:
            The Task about to be executed.
        run:
            The Run object representing this execution attempt.

        Returns
        -------
        bool | None
            True to allow execution (this plugin never vetoes execution).

        Notes
        -----
        - Timeout is read from task.task_metadata['timeout_seconds']
        - Sets run.timeout_override as a dynamic attribute (not persisted to DB)
        - Executor must check for timeout_override and honor it
        - If timeout_seconds is not set or invalid, uses default timeout
        """
        # Check if timeout is configured in task metadata
        if not task.task_metadata or "timeout_seconds" not in task.task_metadata:
            return True  # Allow execution with default timeout

        timeout_seconds = task.task_metadata.get("timeout_seconds")

        # Validate timeout value
        if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            logger.warning(
                "timeout.invalid_config",
                task_id=task.id,
                task_name=task.name,
                run_id=run.id,
                timeout_seconds=timeout_seconds,
                msg=f"Invalid timeout_seconds in task metadata: {timeout_seconds}",
            )
            return True  # Allow execution with default timeout

        # Set timeout override on the Run object (dynamic attribute, not persisted)
        # The executor will check this before calling subprocess.run()
        run.timeout_override = int(timeout_seconds)  # type: ignore[attr-defined]

        logger.info(
            "timeout.override_set",
            task_id=task.id,
            task_name=task.name,
            run_id=run.id,
            timeout_seconds=timeout_seconds,
            msg=f"Timeout override set to {timeout_seconds}s",
        )

        return True  # Allow execution


# Export a singleton instance for pluggy to register
timeout_plugin = TimeoutPlugin()
