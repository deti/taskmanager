"""Health and info endpoints for operational monitoring.

This module provides operational endpoints for deployment orchestrators
and operators to monitor application health and retrieve system information.

Endpoints:
    - GET /api/health — Comprehensive health check (DB, scheduler, uptime)
    - GET /api/info — Version and non-sensitive configuration summary
"""

import time

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from taskmanager.database import check_db_connection
from taskmanager.settings import get_settings, get_version


router = APIRouter(prefix="/api", tags=["health"])


def _get_startup_time() -> float | None:
    """Get the application startup timestamp.

    This function uses a late import to avoid circular dependencies.
    APP_STARTUP_TIME is set in app.py during lifespan startup.

    Returns:
        float | None: Unix timestamp of app startup, or None if not yet set.
    """
    # Late import to avoid circular dependency
    from taskmanager.api import app

    return app.APP_STARTUP_TIME


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Health check endpoint",
    description="Comprehensive health check including database connectivity, "
    "scheduler status, and uptime. Returns 503 Service Unavailable if any "
    "critical component is unhealthy.",
    responses={
        200: {
            "description": "All health checks passed",
            "content": {
                "application/json": {
                    "example": {
                        "status": "healthy",
                        "checks": {
                            "database": "ok",
                            "scheduler": "not_configured",
                        },
                        "uptime_seconds": 42,
                    }
                }
            },
        },
        503: {
            "description": "One or more health checks failed",
            "content": {
                "application/json": {
                    "example": {
                        "status": "unhealthy",
                        "checks": {
                            "database": "error",
                            "scheduler": "not_configured",
                        },
                        "uptime_seconds": 42,
                    }
                }
            },
        },
    },
)
async def health_check() -> JSONResponse:
    """Perform comprehensive health check.

    Checks:
        - Database connectivity (using check_db_connection)
        - Scheduler status (returns "not_configured" until APScheduler is integrated)
        - Application uptime (seconds since startup)

    Returns:
        JSONResponse: Health status with 200 OK (healthy) or 503 Service Unavailable (unhealthy).
    """
    # Check database connectivity
    db_status = "ok" if check_db_connection() else "error"

    # Check scheduler status (stub for now - will be implemented when APScheduler is wired up)
    scheduler_status = "not_configured"

    # Calculate uptime using startup time from app.py
    startup_time = _get_startup_time()
    uptime = 0 if startup_time is None else int(time.time() - startup_time)

    # Build health check response
    overall_status = "healthy" if db_status == "ok" else "unhealthy"
    http_status = status.HTTP_200_OK if overall_status == "healthy" else status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(
        status_code=http_status,
        content={
            "status": overall_status,
            "checks": {
                "database": db_status,
                "scheduler": scheduler_status,
            },
            "uptime_seconds": uptime,
        },
    )


@router.get(
    "/info",
    status_code=status.HTTP_200_OK,
    summary="Application info endpoint",
    description="Returns version information and non-sensitive configuration summary. "
    "Useful for operators to verify deployment version and environment.",
    responses={
        200: {
            "description": "Application information",
            "content": {
                "application/json": {
                    "example": {
                        "version": "0.1.0",
                        "environment": "development",
                        "app_name": "taskmanager",
                    }
                }
            },
        },
    },
)
async def info() -> dict[str, str]:
    """Return application version and configuration summary.

    Returns only non-sensitive configuration values. Sensitive values
    (db_url, secrets, etc.) are explicitly excluded.

    Returns:
        dict: Application info with version, environment, and app_name.
    """
    settings = get_settings()
    version = get_version()

    return {
        "version": version,
        "environment": settings.environment,
        "app_name": settings.app_name,
    }
