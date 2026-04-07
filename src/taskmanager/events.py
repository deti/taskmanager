"""Internal event bus for task lifecycle events.

This module provides a lightweight, thread-safe event bus for coordinating
task lifecycle events across components without tight coupling.

Event Types:
    TASK_STARTED: Task execution has started
    TASK_COMPLETED: Task execution finished successfully
    TASK_FAILED: Task execution failed
    TASK_TIMEOUT: Task execution exceeded timeout
    SCHEDULE_TRIGGERED: Scheduled task was triggered
    SCHEDULE_MISSED: Scheduled task missed its execution window

Usage:
    from taskmanager.events import get_event_bus, TASK_STARTED

    # Get the singleton event bus
    bus = get_event_bus()

    # Register a handler
    def handle_task_start(payload: dict[str, Any]) -> None:
        print(f"Task {payload['task_id']} started")

    bus.on(TASK_STARTED, handle_task_start)

    # Emit an event
    bus.emit(TASK_STARTED, {"task_id": "123", "task_name": "backup"})

    # Unregister a handler
    bus.off(TASK_STARTED, handle_task_start)
"""

import threading
from collections import defaultdict
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from taskmanager.logging import get_logger


# Event type constants
TASK_STARTED = "task.started"
TASK_COMPLETED = "task.completed"
TASK_FAILED = "task.failed"
TASK_TIMEOUT = "task.timeout"
SCHEDULE_TRIGGERED = "schedule.triggered"
SCHEDULE_MISSED = "schedule.missed"

logger = get_logger(__name__)


class EventBus:
    """Thread-safe event bus for pub/sub messaging.

    Handlers are called synchronously in the order they were registered.
    Exceptions in handlers are logged but do not propagate to the emitter
    or affect other handlers.
    """

    def __init__(self) -> None:
        """Initialize the event bus."""
        self._handlers: dict[str, list[Callable[[dict[str, Any]], None]]] = defaultdict(
            list
        )
        self._lock = threading.Lock()

    def on(self, event_type: str, handler: Callable[[dict[str, Any]], None]) -> None:
        """Register a handler for an event type.

        Args:
            event_type: The event type to listen for (e.g., TASK_STARTED).
            handler: Callable that receives the event payload dict.

        Thread-safe: Multiple threads can register handlers concurrently.
        """
        with self._lock:
            if handler not in self._handlers[event_type]:
                self._handlers[event_type].append(handler)

    def off(self, event_type: str, handler: Callable[[dict[str, Any]], None]) -> None:
        """Unregister a handler for an event type.

        Args:
            event_type: The event type to stop listening for.
            handler: The handler to remove.

        Thread-safe: Multiple threads can unregister handlers concurrently.

        Note:
            If the handler was not registered, this is a no-op.
        """
        with self._lock:
            if handler in self._handlers[event_type]:
                self._handlers[event_type].remove(handler)

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        """Emit an event to all registered handlers.

        Args:
            event_type: The event type to emit.
            payload: Event payload dict passed to handlers.

        Thread-safe: Multiple threads can emit events concurrently.

        Exception Handling:
            Handler exceptions are logged but do not propagate. Other handlers
            will still be called even if one fails.
        """
        # Snapshot handlers under lock to avoid holding lock during handler execution
        with self._lock:
            handlers = list(self._handlers[event_type])

        for handler in handlers:
            try:
                handler(payload)
            except Exception as exc:
                # Log exception but don't crash the emitter
                logger.error(
                    "event_handler_exception",
                    event_type=event_type,
                    handler=handler.__name__,
                    error=str(exc),
                    exc_info=True,
                )


@lru_cache(maxsize=1)
def get_event_bus() -> EventBus:
    """Get the singleton EventBus instance.

    Returns:
        The global EventBus instance.

    Thread-safe: lru_cache ensures only one instance is created.
    """
    return EventBus()
