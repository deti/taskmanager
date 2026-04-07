"""Tests for Run history API endpoints.

This module tests all run-related API endpoints including list with filters,
get details, and get logs.
"""

import os
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from taskmanager.api.app import create_app
from taskmanager.api.deps import get_db
from taskmanager.database import Base
from taskmanager.models import Run, RunStatus, Task


@pytest.fixture
def test_engine() -> Generator[Engine, None, None]:
    """Create a test database engine with thread-safe SQLite configuration.

    Returns:
        Engine: A SQLAlchemy engine configured for testing.
    """
    # Ensure we're in test environment
    os.environ["ENVIRONMENT"] = "test"

    # Create in-memory SQLite database with StaticPool to share across connections
    # StaticPool ensures all connections use the same in-memory database
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # Share the same connection across threads
    )
    Base.metadata.create_all(engine)

    yield engine

    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def test_session(test_engine: Engine) -> Generator[Session, None, None]:
    """Create a test database session.

    Args:
        test_engine: Test database engine fixture.

    Returns:
        Session: A SQLAlchemy session for direct database access in tests.
    """
    connection = test_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(test_engine: Engine) -> TestClient:
    """Create a FastAPI test client with database dependency override.

    Args:
        test_engine: Test database engine fixture.

    Returns:
        TestClient: A test client configured to use the test database.
    """
    # Ensure we're in test environment
    os.environ["ENVIRONMENT"] = "test"

    # Create app and override get_db dependency
    app = create_app()

    # Create a session factory for the test
    test_session_local = sessionmaker(bind=test_engine, expire_on_commit=False)

    def override_get_db():
        """Override get_db to use test database."""
        session = test_session_local()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    return TestClient(app)


@pytest.fixture
def sample_task(test_session: Session) -> Task:
    """Create a sample task for testing.

    Args:
        test_session: Test database session.

    Returns:
        Task: A created task instance.
    """
    task = Task(
        name="sample-task",
        command="echo 'test'",
        description="Sample task for testing",
        shell="/bin/sh",
    )
    test_session.add(task)
    test_session.commit()
    test_session.refresh(task)
    return task


@pytest.fixture
def sample_runs(test_session: Session, sample_task: Task) -> list[Run]:
    """Create sample runs for testing.

    Creates runs in different states for comprehensive testing.

    Args:
        test_session: Test database session.
        sample_task: Sample task fixture.

    Returns:
        list[Run]: List of created run instances.
    """
    runs = [
        Run(
            task_id=sample_task.id,
            command_snapshot="echo 'test 1'",
            status=RunStatus.SUCCESS,
            exit_code=0,
            stdout="test 1 output",
            stderr="",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            duration_ms=100,
        ),
        Run(
            task_id=sample_task.id,
            command_snapshot="echo 'test 2'",
            status=RunStatus.FAILED,
            exit_code=1,
            stdout="",
            stderr="test 2 error",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            duration_ms=200,
        ),
        Run(
            task_id=sample_task.id,
            command_snapshot="echo 'test 3'",
            status=RunStatus.RUNNING,
            exit_code=None,
            stdout="partial output",
            stderr="",
            started_at=datetime.now(UTC),
            finished_at=None,
            duration_ms=None,
        ),
    ]

    for run in runs:
        test_session.add(run)
    test_session.commit()

    for run in runs:
        test_session.refresh(run)

    return runs


# ============================================================================
# List Runs Tests (Task 2.1)
# ============================================================================


def test_list_runs_empty(client: TestClient) -> None:
    """Test GET /api/runs returns empty list when no runs exist."""
    response = client.get("/api/runs")

    assert response.status_code == 200
    json_data = response.json()
    assert json_data["items"] == []
    assert json_data["total"] == 0
    assert json_data["page"] == 1
    assert json_data["page_size"] == 20


def test_list_runs_without_filters(client: TestClient, sample_runs: list[Run]) -> None:
    """Test GET /api/runs returns all runs without filters."""
    response = client.get("/api/runs")

    assert response.status_code == 200
    json_data = response.json()
    assert len(json_data["items"]) == 3
    assert json_data["total"] == 3
    assert json_data["page"] == 1
    assert json_data["page_size"] == 20

    # Verify run data is present
    run_ids = {run["id"] for run in json_data["items"]}
    assert run_ids == {run.id for run in sample_runs}


def test_list_runs_filter_by_task_id(
    client: TestClient, sample_task: Task, sample_runs: list[Run], test_session: Session
) -> None:
    """Test GET /api/runs?task_id=X filters by task ID."""
    # Create another task with runs
    other_task = Task(name="other-task", command="echo 'other'", shell="/bin/sh")
    test_session.add(other_task)
    test_session.commit()
    test_session.refresh(other_task)

    other_run = Run(
        task_id=other_task.id,
        command_snapshot="echo 'other'",
        status=RunStatus.SUCCESS,
        exit_code=0,
        stdout="other output",
        stderr="",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        duration_ms=50,
    )
    test_session.add(other_run)
    test_session.commit()

    # Filter by sample_task.id
    response = client.get(f"/api/runs?task_id={sample_task.id}")

    assert response.status_code == 200
    json_data = response.json()
    assert len(json_data["items"]) == 3
    assert json_data["total"] == 3

    # Verify all returned runs belong to sample_task
    for run_data in json_data["items"]:
        assert run_data["task_id"] == sample_task.id


def test_list_runs_filter_by_status_success(
    client: TestClient, sample_runs: list[Run]
) -> None:
    """Test GET /api/runs?status=success filters by success status."""
    response = client.get("/api/runs?status=success")

    assert response.status_code == 200
    json_data = response.json()
    assert len(json_data["items"]) == 1
    assert json_data["total"] == 1
    assert json_data["items"][0]["status"] == "success"


def test_list_runs_filter_by_status_failed(
    client: TestClient, sample_runs: list[Run]
) -> None:
    """Test GET /api/runs?status=failed filters by failed status."""
    response = client.get("/api/runs?status=failed")

    assert response.status_code == 200
    json_data = response.json()
    assert len(json_data["items"]) == 1
    assert json_data["total"] == 1
    assert json_data["items"][0]["status"] == "failed"


def test_list_runs_filter_by_status_running(
    client: TestClient, sample_runs: list[Run]
) -> None:
    """Test GET /api/runs?status=running filters by running status."""
    response = client.get("/api/runs?status=running")

    assert response.status_code == 200
    json_data = response.json()
    assert len(json_data["items"]) == 1
    assert json_data["total"] == 1
    assert json_data["items"][0]["status"] == "running"


def test_list_runs_respects_limit(client: TestClient, sample_runs: list[Run]) -> None:
    """Test GET /api/runs?limit=N respects the limit parameter."""
    response = client.get("/api/runs?limit=2")

    assert response.status_code == 200
    json_data = response.json()
    assert len(json_data["items"]) == 2
    assert json_data["total"] == 2
    assert json_data["page_size"] == 2


def test_list_runs_limit_minimum(client: TestClient, sample_runs: list[Run]) -> None:
    """Test GET /api/runs?limit=1 returns single run."""
    response = client.get("/api/runs?limit=1")

    assert response.status_code == 200
    json_data = response.json()
    assert len(json_data["items"]) == 1
    assert json_data["total"] == 1
    assert json_data["page_size"] == 1


def test_list_runs_limit_default(client: TestClient, sample_runs: list[Run]) -> None:
    """Test GET /api/runs without limit uses default of 20."""
    response = client.get("/api/runs")

    assert response.status_code == 200
    json_data = response.json()
    assert json_data["page_size"] == 20


def test_list_runs_combined_filters(
    client: TestClient, sample_task: Task, sample_runs: list[Run]
) -> None:
    """Test GET /api/runs with multiple filters combined."""
    response = client.get(f"/api/runs?task_id={sample_task.id}&status=success&limit=10")

    assert response.status_code == 200
    json_data = response.json()
    assert len(json_data["items"]) == 1
    assert json_data["total"] == 1
    assert json_data["items"][0]["status"] == "success"
    assert json_data["items"][0]["task_id"] == sample_task.id


# ============================================================================
# Get Run Details Tests (Task 2.1)
# ============================================================================


def test_get_run_by_id_success(client: TestClient, sample_runs: list[Run]) -> None:
    """Test GET /api/runs/{id} returns run details."""
    run = sample_runs[0]
    response = client.get(f"/api/runs/{run.id}")

    assert response.status_code == 200
    json_data = response.json()
    assert json_data["id"] == run.id
    assert json_data["task_id"] == run.task_id
    assert json_data["status"] == run.status.value
    assert json_data["exit_code"] == run.exit_code
    assert json_data["stdout"] == run.stdout
    assert json_data["stderr"] == run.stderr
    assert json_data["duration_ms"] == run.duration_ms


def test_get_run_invalid_id_returns_404(client: TestClient) -> None:
    """Test GET /api/runs/{id} with invalid ID returns 404."""
    fake_uuid = "123e4567-e89b-12d3-a456-426614174000"

    response = client.get(f"/api/runs/{fake_uuid}")

    assert response.status_code == 404
    json_data = response.json()
    assert json_data["error"] == "Not Found"
    assert fake_uuid in json_data["message"]
    assert json_data["detail"]["run_id"] == fake_uuid


def test_get_run_all_fields_populated(client: TestClient, sample_runs: list[Run]) -> None:
    """Test GET /api/runs/{id} returns all expected fields."""
    run = sample_runs[0]
    response = client.get(f"/api/runs/{run.id}")

    assert response.status_code == 200
    json_data = response.json()

    # Verify all expected fields are present
    required_fields = [
        "id",
        "task_id",
        "status",
        "exit_code",
        "stdout",
        "stderr",
        "started_at",
        "finished_at",
        "duration_ms",
    ]
    for field in required_fields:
        assert field in json_data


# ============================================================================
# Get Run Logs Tests (Task 2.1)
# ============================================================================


def test_get_run_logs_success(client: TestClient, sample_runs: list[Run]) -> None:
    """Test GET /api/runs/{id}/logs returns stdout and stderr."""
    run = sample_runs[0]
    response = client.get(f"/api/runs/{run.id}/logs")

    assert response.status_code == 200
    json_data = response.json()
    assert "stdout" in json_data
    assert "stderr" in json_data
    assert json_data["stdout"] == run.stdout
    assert json_data["stderr"] == run.stderr


def test_get_run_logs_with_stderr(client: TestClient, sample_runs: list[Run]) -> None:
    """Test GET /api/runs/{id}/logs returns logs for run with stderr."""
    # Get the failed run (index 1) which has stderr
    run = sample_runs[1]
    response = client.get(f"/api/runs/{run.id}/logs")

    assert response.status_code == 200
    json_data = response.json()
    assert json_data["stdout"] == ""
    assert json_data["stderr"] == "test 2 error"


def test_get_run_logs_with_running_task(client: TestClient, sample_runs: list[Run]) -> None:
    """Test GET /api/runs/{id}/logs works for running task with partial output."""
    # Get the running run (index 2)
    run = sample_runs[2]
    response = client.get(f"/api/runs/{run.id}/logs")

    assert response.status_code == 200
    json_data = response.json()
    assert json_data["stdout"] == "partial output"
    assert json_data["stderr"] == ""


def test_get_run_logs_invalid_id_returns_404(client: TestClient) -> None:
    """Test GET /api/runs/{id}/logs with invalid ID returns 404."""
    fake_uuid = "123e4567-e89b-12d3-a456-426614174000"

    response = client.get(f"/api/runs/{fake_uuid}/logs")

    assert response.status_code == 404
    json_data = response.json()
    assert json_data["error"] == "Not Found"
    assert fake_uuid in json_data["message"]


def test_get_run_logs_empty_output(
    client: TestClient, test_session: Session, sample_task: Task
) -> None:
    """Test GET /api/runs/{id}/logs handles empty stdout/stderr."""
    # Create a run with empty output
    run = Run(
        task_id=sample_task.id,
        command_snapshot="true",
        status=RunStatus.SUCCESS,
        exit_code=0,
        stdout="",
        stderr="",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        duration_ms=10,
    )
    test_session.add(run)
    test_session.commit()
    test_session.refresh(run)

    response = client.get(f"/api/runs/{run.id}/logs")

    assert response.status_code == 200
    json_data = response.json()
    assert json_data["stdout"] == ""
    assert json_data["stderr"] == ""
