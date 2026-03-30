"""CLI command to serve the API proxy."""

import logging
from typing import Annotated

import typer
import uvicorn

from taskmanager.main import app
from taskmanager.settings import get_settings


logger = logging.getLogger(__name__)


def serve(
    host: Annotated[
        str | None,
        typer.Option("--host", "-h", help="Host address to bind the API server."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", "-p", help="Port number to bind the API server."),
    ] = None,
) -> None:
    """Start the API server with configured host and port."""
    settings = get_settings()

    # Use CLI parameters if provided, otherwise fall back to settings
    server_host = host if host is not None else settings.host
    server_port = port if port is not None else settings.port

    # Configure logging
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info(
        f"Starting API server on {server_host}:{server_port}",
    )

    uvicorn.run(
        app,
        host=server_host,
        port=server_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    serve()
