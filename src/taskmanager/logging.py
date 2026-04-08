"""Structured logging setup using structlog.

This module configures structlog for the taskmanager application, supporting both
human-readable colored text output and machine-parseable JSON output.

Usage:
    # At application startup (main.py, CLI entry points):
    from taskmanager.logging import setup_logging
    from taskmanager.settings import get_settings

    setup_logging(get_settings())

    # In application code:
    from taskmanager.logging import get_logger

    logger = get_logger(__name__)
    logger.info("task_started", task_id=task.id, task_name=task.name)
    logger.error("task_failed", task_id=task.id, error=str(exc))

Configuration:
    - log_level: Sets the minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    - log_format: Output format - "text" for colored console, "json" for JSON lines

Standard processors applied:
    - add_log_level: Adds log level to each event
    - merge_contextvars: Merges contextvars into log context
    - TimeStamper: Adds ISO 8601 timestamp
    - CallsiteParameterAdder: Adds function name and line number
    - format_exc_info: Formats exception info if present
    - StackInfoRenderer: Renders stack traces when requested
"""

import logging
import sys
from typing import TYPE_CHECKING, Any

import structlog


if TYPE_CHECKING:
    from structlog.types import Processor

from taskmanager.settings import Settings


def setup_logging(settings: Settings) -> None:
    """Configure structlog based on application settings.

    Args:
        settings: Application settings containing log_level and log_format.

    Side effects:
        - Configures structlog processors and renderer
        - Sets stdlib logging level
        - Configures log output destination (stdout)
    """
    # Convert log level string to logging constant
    log_level = getattr(logging, settings.log_level)

    # Choose renderer based on format setting
    renderer: Processor
    if settings.log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        # Text format with colors for terminal output
        renderer = structlog.dev.ConsoleRenderer(
            colors=True,
            exception_formatter=structlog.dev.plain_traceback,
        )

    # Configure structlog processors
    structlog.configure(
        processors=[
            # Add log level to event dict
            structlog.stdlib.add_log_level,
            # Merge contextvars into the event dict
            structlog.contextvars.merge_contextvars,
            # Add ISO 8601 timestamp
            structlog.processors.TimeStamper(fmt="iso"),
            # Add callsite parameters (file, line, function)
            structlog.processors.CallsiteParameterAdder(
                parameters=[
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                    structlog.processors.CallsiteParameter.LINENO,
                ]
            ),
            # Format exception info if present
            structlog.processors.format_exc_info,
            # Stack info processor (adds stack traces for better debugging)
            structlog.processors.StackInfoRenderer(),
            # Render the final output
            renderer,
        ],
        # Use structlog's logger factory
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        # Wrap stdlib logger for compatibility
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        # Clear context on each log call for thread safety
        cache_logger_on_first_use=False,
    )

    # Configure stdlib logging to match structlog level
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )


def get_logger(name: str | None = None) -> Any:
    """Create a bound structlog logger.

    Args:
        name: Logger name, typically __name__ of the calling module.
              If None, uses the root logger.

    Returns:
        A bound structlog logger instance that can be used for logging events.

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("operation_completed", duration=1.23, status="success")
    """
    return structlog.get_logger(name)
