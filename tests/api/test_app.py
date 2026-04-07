"""Tests for FastAPI application factory and configuration.

This module tests the app factory, exception handlers, middleware,
and core endpoints like /health and OpenAPI docs.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from taskmanager.api.app import create_app
from taskmanager.exceptions import (
    DuplicateTaskError,
    ScheduleNotFoundError,
    TaskNotFoundError,
)


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI app instance for testing.

    Returns:
        FastAPI: A configured application instance.
    """
    return create_app()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create a test client for the FastAPI app.

    Args:
        app: The FastAPI application instance.

    Returns:
        TestClient: A test client for making requests.
    """
    return TestClient(app)


def test_create_app_returns_fastapi_instance() -> None:
    """Test that create_app() returns a FastAPI instance."""
    app = create_app()
    assert isinstance(app, FastAPI)
    assert app.title == "TaskManager API"
    assert app.version == "0.1.0"


def test_health_endpoint_returns_200(client: TestClient) -> None:
    """Test that /health endpoint returns 200 with status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_docs_accessible(client: TestClient) -> None:
    """Test that OpenAPI documentation endpoints are accessible."""
    # Test /docs (Swagger UI) - returns HTML
    docs_response = client.get("/docs")
    assert docs_response.status_code == 200
    assert "text/html" in docs_response.headers["content-type"]

    # Test /openapi.json (OpenAPI schema) - returns JSON
    openapi_response = client.get("/openapi.json")
    assert openapi_response.status_code == 200
    schema = openapi_response.json()
    assert schema["info"]["title"] == "TaskManager API"
    assert schema["info"]["version"] == "0.1.0"
    assert "/health" in schema["paths"]


def test_cors_headers_present(client: TestClient) -> None:
    """Test that CORS headers are present in responses."""
    # Make a request with Origin header
    response = client.get(
        "/health",
        headers={"Origin": "http://localhost:3000"},
    )

    # Check CORS headers are present
    assert response.status_code == 200
    assert "access-control-allow-origin" in response.headers
    # When an origin is provided, CORS middleware echoes it back (not "*")
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_preflight_request(client: TestClient) -> None:
    """Test that CORS preflight (OPTIONS) requests work correctly."""
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    # Preflight should return 200 with CORS headers
    assert response.status_code == 200
    assert "access-control-allow-origin" in response.headers
    assert "access-control-allow-methods" in response.headers


def test_duplicate_task_error_maps_to_409(app: FastAPI, client: TestClient) -> None:
    """Test that DuplicateTaskError is mapped to 409 Conflict."""

    # Add a test endpoint that raises DuplicateTaskError
    @app.get("/test/duplicate")
    async def test_duplicate() -> None:
        raise DuplicateTaskError("test-task")

    response = client.get("/test/duplicate")

    assert response.status_code == 409
    json_data = response.json()
    assert json_data["error"] == "Conflict"
    assert "test-task" in json_data["message"]
    assert json_data["detail"]["task_name"] == "test-task"


def test_task_not_found_error_maps_to_404(app: FastAPI, client: TestClient) -> None:
    """Test that TaskNotFoundError is mapped to 404 Not Found."""

    # Add a test endpoint that raises TaskNotFoundError
    @app.get("/test/task-not-found")
    async def test_task_not_found() -> None:
        raise TaskNotFoundError("123e4567-e89b-12d3-a456-426614174000")

    response = client.get("/test/task-not-found")

    assert response.status_code == 404
    json_data = response.json()
    assert json_data["error"] == "Not Found"
    assert "123e4567-e89b-12d3-a456-426614174000" in json_data["message"]
    assert json_data["detail"]["task_id"] == "123e4567-e89b-12d3-a456-426614174000"


def test_schedule_not_found_error_maps_to_404(
    app: FastAPI, client: TestClient
) -> None:
    """Test that ScheduleNotFoundError is mapped to 404 Not Found."""

    # Add a test endpoint that raises ScheduleNotFoundError
    @app.get("/test/schedule-not-found")
    async def test_schedule_not_found() -> None:
        raise ScheduleNotFoundError("123e4567-e89b-12d3-a456-426614174001")

    response = client.get("/test/schedule-not-found")

    assert response.status_code == 404
    json_data = response.json()
    assert json_data["error"] == "Not Found"
    assert "123e4567-e89b-12d3-a456-426614174001" in json_data["message"]
    assert json_data["detail"]["schedule_id"] == "123e4567-e89b-12d3-a456-426614174001"


def test_exception_handlers_registered_before_routers() -> None:
    """Test that exception handlers are registered in the correct order.

    This is a smoke test to ensure create_app() completes without errors,
    which would fail if exception handlers were registered after routers
    (when routers are added in Wave 3).
    """
    app = create_app()

    # Verify exception handlers are registered
    assert DuplicateTaskError in app.exception_handlers
    assert TaskNotFoundError in app.exception_handlers
    assert ScheduleNotFoundError in app.exception_handlers


def test_health_endpoint_in_openapi_schema(client: TestClient) -> None:
    """Test that /health endpoint appears in OpenAPI schema with correct metadata."""
    openapi_response = client.get("/openapi.json")
    schema = openapi_response.json()

    # Check /health endpoint is documented
    assert "/health" in schema["paths"]
    health_endpoint = schema["paths"]["/health"]

    # Check it has a GET operation
    assert "get" in health_endpoint

    # Check it's tagged as "health"
    assert "tags" in health_endpoint["get"]
    assert "health" in health_endpoint["get"]["tags"]
