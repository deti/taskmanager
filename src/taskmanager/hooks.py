"""Hook processor for executing actions in response to events.

This module provides the HookProcessor that listens to EventBus events
and executes configured actions (shell commands, webhooks, logs).
"""

import json
import subprocess
from functools import lru_cache
from typing import Any

import httpx

from taskmanager.database import get_db
from taskmanager.events import get_event_bus
from taskmanager.logging import get_logger
from taskmanager.models import ActionType
from taskmanager.services.hook_service import list_hooks

logger = get_logger(__name__)


class HookProcessor:
    """Processes events and executes matching hook actions.

    The processor registers handlers for all event types and queries
    enabled hooks matching each event. Actions are executed with
    template variable substitution and proper error handling.
    """

    def __init__(self) -> None:
        """Initialize the hook processor and register event handlers."""
        self._event_bus = get_event_bus()

        # Register a universal handler for all events
        # We'll filter at execution time based on event_type
        self._registered_events: set[str] = set()

    def register_event_type(self, event_type: str) -> None:
        """Register a handler for a specific event type.

        Parameters
        ----------
        event_type:
            The event type to listen for.
        """
        if event_type not in self._registered_events:
            self._event_bus.on(event_type, self._on_event)
            self._registered_events.add(event_type)

    def _on_event(self, payload: dict[str, Any]) -> None:
        """Handle incoming events by executing matching hooks.

        Parameters
        ----------
        payload:
            Event payload dict containing event details.
            Expected keys: event_type, task_id, run_id, etc.
        """
        event_type = payload.get("event_type", "unknown")

        # Query all enabled hooks matching this event type
        with get_db() as session:
            all_hooks = list_hooks(session, enabled=True)

        # Filter hooks by event_type and task_filter
        matching_hooks = [
            hook
            for hook in all_hooks
            if hook.event_type == event_type and self._matches_filter(hook, payload)
        ]

        if not matching_hooks:
            logger.debug(
                "no_matching_hooks",
                event_type=event_type,
                task_id=payload.get("task_id"),
            )
            return

        # Execute each matching hook
        for hook in matching_hooks:
            try:
                self._execute_action(hook, payload)
            except Exception as exc:
                # Log error but don't crash — hook failures are non-fatal
                logger.error(
                    "hook_execution_failed",
                    hook_name=hook.name,
                    event_type=event_type,
                    error=str(exc),
                    exc_info=True,
                )

    def _matches_filter(self, hook: Any, payload: dict[str, Any]) -> bool:
        """Check if hook's task_filter matches the event payload.

        Parameters
        ----------
        hook:
            The Hook model instance.
        payload:
            Event payload dict.

        Returns
        -------
        bool
            True if hook matches (task_filter is None OR matches task_id).
        """
        # Global hook (task_filter is None) matches all events
        if hook.task_filter is None:
            return True

        # Task-scoped hook matches only if task_id matches
        task_id = payload.get("task_id")
        return bool(hook.task_filter == task_id)

    def _execute_action(self, hook: Any, payload: dict[str, Any]) -> None:
        """Execute the hook's action based on action_type.

        Parameters
        ----------
        hook:
            The Hook model instance.
        payload:
            Event payload dict for template substitution.
        """
        if hook.action_type == ActionType.SHELL:
            self._execute_shell_action(hook, payload)
        elif hook.action_type == ActionType.WEBHOOK:
            self._execute_webhook_action(hook, payload)
        elif hook.action_type == ActionType.LOG:
            self._execute_log_action(hook, payload)
        else:
            logger.warning(
                "unknown_action_type",
                hook_name=hook.name,
                action_type=hook.action_type,
            )

    def _substitute_template_vars(
        self, template: str, payload: dict[str, Any]
    ) -> str:
        """Substitute template variables in a string.

        Parameters
        ----------
        template:
            String with {variable} placeholders.
        payload:
            Event payload dict with values.

        Returns
        -------
        str
            String with substituted values.

        Supported variables:
            {task_name}, {task_id}, {run_id}, {exit_code}, {duration_ms}, {status}
        """
        # Build substitution dict
        subs = {
            "task_name": payload.get("task_name", ""),
            "task_id": payload.get("task_id", ""),
            "run_id": payload.get("run_id", ""),
            "exit_code": str(payload.get("exit_code", "")),
            "duration_ms": str(payload.get("duration_ms", "")),
            "status": payload.get("status", ""),
            "event_type": payload.get("event_type", ""),
        }

        result = template
        for key, value in subs.items():
            result = result.replace(f"{{{key}}}", str(value))

        return result

    def _execute_shell_action(self, hook: Any, payload: dict[str, Any]) -> None:
        """Execute a shell command action.

        Parameters
        ----------
        hook:
            The Hook model instance.
        payload:
            Event payload dict for template substitution.
        """
        try:
            config = json.loads(hook.action_config)
            command_template = config["command"]

            # Substitute template variables
            command = self._substitute_template_vars(command_template, payload)

            logger.info(
                "executing_shell_hook",
                hook_name=hook.name,
                command=command,
            )

            # Execute command
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,  # 30 second timeout
            )

            logger.info(
                "shell_hook_completed",
                hook_name=hook.name,
                exit_code=result.returncode,
                stdout_length=len(result.stdout),
                stderr_length=len(result.stderr),
            )

            if result.returncode != 0:
                logger.warning(
                    "shell_hook_failed",
                    hook_name=hook.name,
                    exit_code=result.returncode,
                    stderr=result.stderr[:500],  # Truncate to avoid log spam
                )

        except subprocess.TimeoutExpired:
            logger.error(
                "shell_hook_timeout",
                hook_name=hook.name,
                command=command,
            )
        except Exception as exc:
            logger.error(
                "shell_hook_exception",
                hook_name=hook.name,
                error=str(exc),
                exc_info=True,
            )

    def _execute_webhook_action(self, hook: Any, payload: dict[str, Any]) -> None:
        """Execute a webhook POST action.

        Parameters
        ----------
        hook:
            The Hook model instance.
        payload:
            Event payload dict to POST as JSON.
        """
        try:
            config = json.loads(hook.action_config)
            url = config["url"]

            logger.info(
                "executing_webhook_hook",
                hook_name=hook.name,
                url=url,
            )

            # POST the full payload as JSON
            response = httpx.post(
                url,
                json=payload,
                timeout=10.0,  # 10 second timeout
            )

            logger.info(
                "webhook_hook_completed",
                hook_name=hook.name,
                url=url,
                status_code=response.status_code,
            )

            if response.status_code >= 400:
                logger.warning(
                    "webhook_hook_failed",
                    hook_name=hook.name,
                    url=url,
                    status_code=response.status_code,
                    response_text=response.text[:500],  # Truncate
                )

        except httpx.TimeoutException:
            logger.error(
                "webhook_hook_timeout",
                hook_name=hook.name,
                url=url,
            )
        except Exception as exc:
            logger.error(
                "webhook_hook_exception",
                hook_name=hook.name,
                url=url,
                error=str(exc),
                exc_info=True,
            )

    def _execute_log_action(self, hook: Any, payload: dict[str, Any]) -> None:
        """Execute a structured log action.

        Parameters
        ----------
        hook:
            The Hook model instance.
        payload:
            Event payload dict to include in log.
        """
        try:
            config = json.loads(hook.action_config)
            level = config.get("level", "info").lower()

            # Log the event with full payload
            log_func = getattr(logger, level, logger.info)
            log_func(
                "hook_log_action",
                hook_name=hook.name,
                **payload,
            )

        except Exception as exc:
            logger.error(
                "log_hook_exception",
                hook_name=hook.name,
                error=str(exc),
                exc_info=True,
            )


@lru_cache(maxsize=1)
def get_hook_processor() -> HookProcessor:
    """Get the singleton HookProcessor instance.

    Returns
    -------
    HookProcessor
        The global HookProcessor instance.
    """
    return HookProcessor()
