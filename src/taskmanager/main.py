from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from taskmanager.logging import setup_logging
from taskmanager.settings import get_settings


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifespan events.

    Startup: Initialize logging configuration.
    Shutdown: Cleanup tasks run after this context exits.
    """
    # Startup: Configure logging before request processing
    setup_logging(get_settings())
    yield
    # Shutdown: Add cleanup tasks here if needed


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Hello World"}
