"""Tests for health and info operational endpoints.

This module tests the health check and info endpoints used by deployment
orchestrators and operators to monitor application health and retrieve
system information.

Test Coverage:
    - Health endpoint happy path (200 OK when healthy)
    - Health endpoint unhealthy path (503 when DB unreachable)
    - Health endpoint uptime calculation
    - Info endpoint basic functionality
    - Info endpoint sensitive data exclusion
    - OpenAPI schema documentation
"""

import os
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from taskmanager.api.app import create_app
from taskmanager.database import Base


@pytest.fixture
def test_db_healthy() -> Iterator[Session]:
    """Create an in-memory SQLite database session for testing (healthy DB).

    This fixture creates a fresh database for each test, ensuring isolation.
    The database is automatically cleaned up after the test completes.

    Yields:
        Session: A SQLAlchemy session connected to an in-memory database.
    """
    # Ensure we're in test environment
    os.environ["ENVIRONMENT"] = "test"

    # Create in-memory SQLite database
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    # Create session factory and session
    session_factory = sessionmaker(bind=engine)
    session = session_factory()

    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client_healthy() -> TestClient:
    """Create a FastAPI test client with a healthy database.

    Returns:
        TestClient: A test client for making requests to the FastAPI app.
    """
    # Ensure we're in test environment
    os.environ["ENVIRONMENT"] = "test"

    app = create_app()
    return TestClient(app)


@pytest.fixture
def client_unhealthy() -> TestClient:
    """Create a FastAPI test client with an unreachable database.

    This fixture overrides the database URL to point to a nonexistent path,
    simulating a database connectivity failure.

    Returns:
        TestClient: A test client with unhealthy database configuration.
    """
    # Set environment to test with invalid DB URL
    os.environ["ENVIRONMENT"] = "test"
    os.environ["DB_URL"] = "sqlite:////nonexistent/path/db.sqlite"

    try:
        app = create_app()
        client = TestClient(app)
        yield client
    finally:
        # Clean up environment variable
        if "DB_URL" in os.environ:
            del os.environ["DB_URL"]


def test_health_endpoint_returns_200_when_healthy(client_healthy: TestClient) -> None:
    """Test GET /api/health returns 200 with healthy status when DB is reachable.

    Verifies:
        - Status code is 200 OK
        - Response status is "healthy"
        - Database check is "ok"
        - Scheduler status is present (stub value)
        - Uptime is >= 0
    """
    response = client_healthy.get("/api/health")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "healthy"
    assert data["checks"]["database"] == "ok"
    assert "scheduler" in data["checks"]
    assert data["uptime_seconds"] >= 0


def test_health_endpoint_returns_503_when_db_unreachable(client_unhealthy: TestClient) -> None:
    """Test GET /api/health returns 503 with unhealthy status when DB is unreachable.

    Verifies:
        - Status code is 503 Service Unavailable
        - Response status is "unhealthy"
        - Database check is "error"
        - Uptime is still present
    """
    response = client_unhealthy.get("/api/health")

    assert response.status_code == 503
    data = response.json()

    assert data["status"] == "unhealthy"
    assert data["checks"]["database"] == "error"
    assert "uptime_seconds" in data


def test_health_endpoint_uptime_increases(client_healthy: TestClient) -> None:
    """Test GET /api/health uptime increases over time.

    Verifies:
        - First uptime is >= 0
        - Second uptime is >= first uptime (allowing for same value due to low resolution)
    """
    # First request
    response1 = client_healthy.get("/api/health")
    assert response1.status_code == 200
    uptime1 = response1.json()["uptime_seconds"]
    assert uptime1 >= 0

    # Wait a small amount of time
    time.sleep(0.1)

    # Second request
    response2 = client_healthy.get("/api/health")
    assert response2.status_code == 200
    uptime2 = response2.json()["uptime_seconds"]

    # Uptime should be >= first measurement (may be equal due to integer rounding)
    assert uptime2 >= uptime1


def test_health_endpoint_in_openapi_schema(client_healthy: TestClient) -> None:
    """Test GET /api/health is documented in OpenAPI schema.

    Verifies:
        - /api/health path exists in OpenAPI schema
        - GET method is documented
        - Correct tags are present
        - 200 and 503 responses are documented
    """
    response = client_healthy.get("/openapi.json")
    assert response.status_code == 200
    openapi_schema = response.json()

    # Check path exists
    assert "/api/health" in openapi_schema["paths"]
    health_path = openapi_schema["paths"]["/api/health"]

    # Check GET method exists
    assert "get" in health_path
    health_endpoint = health_path["get"]

    # Check tags
    assert "health" in health_endpoint["tags"]

    # Check responses
    assert "200" in health_endpoint["responses"]
    assert "503" in health_endpoint["responses"]


def test_info_endpoint_returns_200(client_healthy: TestClient) -> None:
    """Test GET /api/info returns 200 with version and config summary.

    Verifies:
        - Status code is 200 OK
        - version field is present and non-empty
        - environment field is present
        - app_name field is present
    """
    response = client_healthy.get("/api/info")

    assert response.status_code == 200
    data = response.json()

    assert "version" in data
    assert data["version"]  # Non-empty
    assert "environment" in data
    assert "app_name" in data


def test_info_endpoint_does_not_leak_sensitive_data(client_healthy: TestClient) -> None:
    """Test GET /api/info does NOT include sensitive configuration.

    Verifies:
        - db_url is NOT in response
        - subprocess_timeout is NOT in response
        - Response contains only whitelisted safe fields
    """
    response = client_healthy.get("/api/info")

    assert response.status_code == 200
    data = response.json()

    # Sensitive fields must NOT be present
    assert "db_url" not in data
    assert "subprocess_timeout" not in data
    assert "default_shell" not in data
    assert "api_host" not in data
    assert "api_port" not in data

    # Only whitelisted fields should be present
    allowed_fields = {"version", "environment", "app_name"}
    assert set(data.keys()) == allowed_fields


def test_info_endpoint_in_openapi_schema(client_healthy: TestClient) -> None:
    """Test GET /api/info is documented in OpenAPI schema.

    Verifies:
        - /api/info path exists in OpenAPI schema
        - GET method is documented
        - Correct tags are present
        - 200 response is documented
    """
    response = client_healthy.get("/openapi.json")
    assert response.status_code == 200
    openapi_schema = response.json()

    # Check path exists
    assert "/api/info" in openapi_schema["paths"]
    info_path = openapi_schema["paths"]["/api/info"]

    # Check GET method exists
    assert "get" in info_path
    info_endpoint = info_path["get"]

    # Check tags
    assert "health" in info_endpoint["tags"]

    # Check response
    assert "200" in info_endpoint["responses"]
