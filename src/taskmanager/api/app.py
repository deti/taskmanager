"""FastAPI application factory.

This module provides the application factory function for creating configured
FastAPI instances with middleware, exception handlers, and route registration.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from taskmanager.api.routers.tasks import router as tasks_router
from taskmanager.exceptions import (
    DuplicateTaskError,
    ScheduleNotFoundError,
    TaskNotFoundError,
)
from taskmanager.logging import setup_logging
from taskmanager.settings import get_settings


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifecycle (startup and shutdown).

    This context manager handles:
    - Startup: Configure logging
    - Shutdown: Clean up resources

    Args:
        _app: The FastAPI application instance (unused but required by signature).

    Yields:
        None: Control returns to the application to handle requests.
    """
    # Startup: Configure logging
    settings = get_settings()
    setup_logging(settings)

    yield

    # Shutdown: Add cleanup logic here if needed in the future


def create_app() -> FastAPI:
    """Create and configure a FastAPI application instance.

    This factory function creates a FastAPI app with:
    - Lifespan context manager for startup/shutdown
    - CORS middleware (allow all origins for development)
    - Global exception handlers for domain exceptions
    - Health check endpoint
    - OpenAPI documentation

    Returns:
        FastAPI: A configured FastAPI application instance.

    Example:
        >>> app = create_app()
        >>> # Use with uvicorn: uvicorn.run(app, host="0.0.0.0", port=8000)
    """
    app = FastAPI(
        title="TaskManager API",
        version="0.1.0",
        description="REST API for task management with scheduling and execution",
        lifespan=lifespan,
    )

    # Configure CORS middleware (allow all origins for development)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Allow all origins in development
        allow_credentials=True,
        allow_methods=["*"],  # Allow all HTTP methods
        allow_headers=["*"],  # Allow all headers
    )

    # Register global exception handlers BEFORE router registration
    @app.exception_handler(DuplicateTaskError)
    async def duplicate_task_handler(
        _request: Request, exc: DuplicateTaskError
    ) -> JSONResponse:
        """Handle DuplicateTaskError by returning 409 Conflict.

        Args:
            _request: The incoming request (unused but required by signature).
            exc: The duplicate task exception.

        Returns:
            JSONResponse with 409 status code and error details.
        """
        return JSONResponse(
            status_code=409,
            content={
                "error": "Conflict",
                "message": exc.message,
                "detail": {"task_name": exc.name},
            },
        )

    @app.exception_handler(TaskNotFoundError)
    async def task_not_found_handler(
        _request: Request, exc: TaskNotFoundError
    ) -> JSONResponse:
        """Handle TaskNotFoundError by returning 404 Not Found.

        Args:
            _request: The incoming request (unused but required by signature).
            exc: The task not found exception.

        Returns:
            JSONResponse with 404 status code and error details.
        """
        return JSONResponse(
            status_code=404,
            content={
                "error": "Not Found",
                "message": exc.message,
                "detail": {"task_id": str(exc.task_id)},
            },
        )

    @app.exception_handler(ScheduleNotFoundError)
    async def schedule_not_found_handler(
        _request: Request, exc: ScheduleNotFoundError
    ) -> JSONResponse:
        """Handle ScheduleNotFoundError by returning 404 Not Found.

        Args:
            _request: The incoming request (unused but required by signature).
            exc: The schedule not found exception.

        Returns:
            JSONResponse with 404 status code and error details.
        """
        return JSONResponse(
            status_code=404,
            content={
                "error": "Not Found",
                "message": exc.message,
                "detail": {"schedule_id": exc.schedule_id},
            },
        )

    # Health check endpoint
    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        """Health check endpoint.

        Returns:
            dict: Status indicator with "ok" value.
        """
        return {"status": "ok"}

    # Register task router
    app.include_router(tasks_router)

    return app
