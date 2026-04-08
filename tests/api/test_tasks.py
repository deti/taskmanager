"""Tests for Task CRUD and execution endpoints.

This module tests all task-related API endpoints including CRUD operations
and task execution.
"""

import os
from collections.abc import Generator

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


# ============================================================================
# Task CRUD Tests (Task 5.1)
# ============================================================================


def test_create_task_success(client: TestClient) -> None:
    """Test POST /api/tasks creates task successfully."""
    task_data = {
        "name": "test-task",
        "command": "echo 'Hello'",
        "description": "A test task",
        "shell": "/bin/bash",
    }

    response = client.post("/api/tasks", json=task_data)

    assert response.status_code == 201
    json_data = response.json()
    assert json_data["name"] == "test-task"
    assert json_data["command"] == "echo 'Hello'"
    assert json_data["description"] == "A test task"
    assert json_data["shell"] == "/bin/bash"
    assert "id" in json_data
    assert "created_at" in json_data
    assert "updated_at" in json_data


def test_create_task_duplicate_name_returns_409(client: TestClient) -> None:
    """Test POST /api/tasks with duplicate name returns 409 Conflict."""
    task_data = {
        "name": "duplicate-task",
        "command": "echo 'First'",
    }

    # Create first task
    response1 = client.post("/api/tasks", json=task_data)
    assert response1.status_code == 201

    # Attempt to create duplicate
    response2 = client.post("/api/tasks", json=task_data)
    assert response2.status_code == 409
    json_data = response2.json()
    assert json_data["error"] == "Conflict"
    assert "duplicate-task" in json_data["message"]
    assert json_data["detail"]["task_name"] == "duplicate-task"


def test_list_tasks_empty(client: TestClient) -> None:
    """Test GET /api/tasks returns empty list initially."""
    response = client.get("/api/tasks")

    assert response.status_code == 200
    json_data = response.json()
    assert json_data["items"] == []
    assert json_data["total"] == 0
    assert json_data["page"] == 1
    assert json_data["page_size"] == 20


def test_list_tasks_with_data(client: TestClient) -> None:
    """Test GET /api/tasks returns paginated list after creating tasks."""
    # Create three tasks
    for i in range(3):
        task_data = {
            "name": f"task-{i}",
            "command": f"echo 'Task {i}'",
            "description": f"Test task {i}",
        }
        response = client.post("/api/tasks", json=task_data)
        assert response.status_code == 201

    # List all tasks
    response = client.get("/api/tasks")
    assert response.status_code == 200
    json_data = response.json()
    assert len(json_data["items"]) == 3
    assert json_data["total"] == 3
    assert json_data["page"] == 1
    assert json_data["page_size"] == 20


def test_list_tasks_pagination(client: TestClient) -> None:
    """Test pagination params (page, page_size) work correctly."""
    # Create 5 tasks
    for i in range(5):
        task_data = {
            "name": f"task-{i}",
            "command": f"echo 'Task {i}'",
        }
        response = client.post("/api/tasks", json=task_data)
        assert response.status_code == 201

    # Test page 1 with page_size=2
    response = client.get("/api/tasks?page=1&page_size=2")
    assert response.status_code == 200
    json_data = response.json()
    assert len(json_data["items"]) == 2
    assert json_data["total"] == 5
    assert json_data["page"] == 1
    assert json_data["page_size"] == 2

    # Test page 2 with page_size=2
    response = client.get("/api/tasks?page=2&page_size=2")
    assert response.status_code == 200
    json_data = response.json()
    assert len(json_data["items"]) == 2
    assert json_data["total"] == 5
    assert json_data["page"] == 2
    assert json_data["page_size"] == 2

    # Test page 3 with page_size=2 (last page, only 1 item)
    response = client.get("/api/tasks?page=3&page_size=2")
    assert response.status_code == 200
    json_data = response.json()
    assert len(json_data["items"]) == 1
    assert json_data["total"] == 5
    assert json_data["page"] == 3
    assert json_data["page_size"] == 2


def test_get_task_by_id_success(client: TestClient) -> None:
    """Test GET /api/tasks/{id} returns task details."""
    # Create a task
    task_data = {
        "name": "get-test-task",
        "command": "echo 'Get me'",
        "description": "Task to retrieve",
    }
    create_response = client.post("/api/tasks", json=task_data)
    assert create_response.status_code == 201
    task_id = create_response.json()["id"]

    # Get task by ID
    response = client.get(f"/api/tasks/{task_id}")
    assert response.status_code == 200
    json_data = response.json()
    assert json_data["id"] == task_id
    assert json_data["name"] == "get-test-task"
    assert json_data["command"] == "echo 'Get me'"
    assert json_data["description"] == "Task to retrieve"


def test_get_task_invalid_id_returns_404(client: TestClient) -> None:
    """Test GET /api/tasks/{id} with invalid ID returns 404."""
    fake_uuid = "123e4567-e89b-12d3-a456-426614174000"

    response = client.get(f"/api/tasks/{fake_uuid}")

    assert response.status_code == 404
    json_data = response.json()
    assert json_data["error"] == "Not Found"
    assert fake_uuid in json_data["message"]
    assert json_data["detail"]["task_id"] == fake_uuid


def test_update_task_success(client: TestClient) -> None:
    """Test PATCH /api/tasks/{id} updates task."""
    # Create a task
    task_data = {
        "name": "update-test-task",
        "command": "echo 'Original'",
        "description": "Original description",
    }
    create_response = client.post("/api/tasks", json=task_data)
    assert create_response.status_code == 201
    task_id = create_response.json()["id"]

    # Update task (partial update)
    update_data = {
        "command": "echo 'Updated'",
        "description": "Updated description",
    }
    response = client.patch(f"/api/tasks/{task_id}", json=update_data)

    assert response.status_code == 200
    json_data = response.json()
    assert json_data["id"] == task_id
    assert json_data["name"] == "update-test-task"  # Unchanged
    assert json_data["command"] == "echo 'Updated'"  # Updated
    assert json_data["description"] == "Updated description"  # Updated


def test_update_task_invalid_id_returns_404(client: TestClient) -> None:
    """Test PATCH /api/tasks/{id} with invalid ID returns 404."""
    fake_uuid = "123e4567-e89b-12d3-a456-426614174000"
    update_data = {"command": "echo 'Will not work'"}

    response = client.patch(f"/api/tasks/{fake_uuid}", json=update_data)

    assert response.status_code == 404
    json_data = response.json()
    assert json_data["error"] == "Not Found"
    assert fake_uuid in json_data["message"]


def test_delete_task_success(client: TestClient) -> None:
    """Test DELETE /api/tasks/{id} removes task."""
    # Create a task
    task_data = {
        "name": "delete-test-task",
        "command": "echo 'Delete me'",
    }
    create_response = client.post("/api/tasks", json=task_data)
    assert create_response.status_code == 201
    task_id = create_response.json()["id"]

    # Delete task
    response = client.delete(f"/api/tasks/{task_id}")
    assert response.status_code == 204

    # Verify task is deleted
    get_response = client.get(f"/api/tasks/{task_id}")
    assert get_response.status_code == 404


def test_delete_task_invalid_id_returns_404(client: TestClient) -> None:
    """Test DELETE /api/tasks/{id} with invalid ID returns 404."""
    fake_uuid = "123e4567-e89b-12d3-a456-426614174000"

    response = client.delete(f"/api/tasks/{fake_uuid}")

    assert response.status_code == 404
    json_data = response.json()
    assert json_data["error"] == "Not Found"
    assert fake_uuid in json_data["message"]


# ============================================================================
# Execution Endpoint Tests (Task 5.2)
# ============================================================================


def test_execute_task_success(client: TestClient, test_engine: Engine) -> None:
    """Test POST /api/tasks/{id}/execute triggers execution successfully."""
    # Create a task with a simple command
    task_data = {
        "name": "exec-test-task",
        "command": "echo 'Hello from task'",
        "shell": "/bin/sh",
    }
    create_response = client.post("/api/tasks", json=task_data)
    assert create_response.status_code == 201
    task_id = create_response.json()["id"]

    # Execute task
    response = client.post(f"/api/tasks/{task_id}/execute")

    assert response.status_code == 202  # Accepted
    json_data = response.json()
    assert "id" in json_data  # Run ID
    assert json_data["task_id"] == task_id
    assert json_data["status"] in ["running", "success"]  # May complete immediately
    assert "started_at" in json_data

    # Verify run was created in database
    run_id = json_data["id"]
    test_session_factory = sessionmaker(bind=test_engine)
    session = test_session_factory()
    run = session.query(Run).filter(Run.id == run_id).first()
    session.close()
    assert run is not None
    assert run.task_id == task_id
    assert run.status in [RunStatus.RUNNING, RunStatus.SUCCESS]


def test_execute_task_captures_output(client: TestClient, test_engine: Engine) -> None:
    """Test task execution captures stdout and stderr correctly."""
    # Create a task that produces output
    task_data = {
        "name": "output-test-task",
        "command": "echo 'stdout output' && echo 'stderr output' >&2",
        "shell": "/bin/bash",
    }
    create_response = client.post("/api/tasks", json=task_data)
    assert create_response.status_code == 201
    task_id = create_response.json()["id"]

    # Execute task
    response = client.post(f"/api/tasks/{task_id}/execute")
    assert response.status_code == 202
    run_id = response.json()["id"]

    # Check run in database (execution should be complete for fast commands)
    test_session_factory = sessionmaker(bind=test_engine)
    session = test_session_factory()
    run = session.query(Run).filter(Run.id == run_id).first()
    session.close()
    assert run is not None
    assert run.status == RunStatus.SUCCESS
    assert "stdout output" in run.stdout
    assert "stderr output" in run.stderr
    assert run.exit_code == 0
    assert run.duration_ms is not None
    assert run.duration_ms >= 0


def test_execute_task_non_zero_exit_code(client: TestClient, test_engine: Engine) -> None:
    """Test task execution with non-zero exit code marks run as FAILED."""
    # Create a task that will fail
    task_data = {
        "name": "fail-test-task",
        "command": "exit 42",
        "shell": "/bin/sh",
    }
    create_response = client.post("/api/tasks", json=task_data)
    assert create_response.status_code == 201
    task_id = create_response.json()["id"]

    # Execute task
    response = client.post(f"/api/tasks/{task_id}/execute")
    assert response.status_code == 202
    run_id = response.json()["id"]

    # Check run in database
    test_session_factory = sessionmaker(bind=test_engine)
    session = test_session_factory()
    run = session.query(Run).filter(Run.id == run_id).first()
    session.close()
    assert run is not None
    assert run.status == RunStatus.FAILED
    assert run.exit_code == 42
    assert run.finished_at is not None


def test_execute_task_invalid_id_returns_404(client: TestClient) -> None:
    """Test POST /api/tasks/{id}/execute with invalid task ID returns 404."""
    fake_uuid = "123e4567-e89b-12d3-a456-426614174000"

    response = client.post(f"/api/tasks/{fake_uuid}/execute")

    assert response.status_code == 404
    json_data = response.json()
    assert json_data["error"] == "Not Found"
    assert fake_uuid in json_data["message"]


def test_execute_task_records_command_snapshot(client: TestClient, test_engine: Engine) -> None:
    """Test that execution records a snapshot of the command."""
    # Create a task
    task_data = {
        "name": "snapshot-test-task",
        "command": "echo 'Original command'",
    }
    create_response = client.post("/api/tasks", json=task_data)
    assert create_response.status_code == 201
    task_id = create_response.json()["id"]

    # Execute task
    response = client.post(f"/api/tasks/{task_id}/execute")
    assert response.status_code == 202
    run_id = response.json()["id"]

    # Verify command snapshot was recorded
    test_session_factory = sessionmaker(bind=test_engine)
    session = test_session_factory()
    run = session.query(Run).filter(Run.id == run_id).first()
    assert run is not None
    assert run.command_snapshot == "echo 'Original command'"

    # Update the task
    update_data = {"command": "echo 'Updated command'"}
    update_response = client.patch(f"/api/tasks/{task_id}", json=update_data)
    assert update_response.status_code == 200

    # Verify run still has original command snapshot (immutable)
    session.refresh(run)
    assert run.command_snapshot == "echo 'Original command'"

    # Verify task has new command
    task = session.query(Task).filter(Task.id == task_id).first()
    assert task is not None
    assert task.command == "echo 'Updated command'"
    session.close()


def test_execute_task_with_true_command(client: TestClient, test_engine: Engine) -> None:
    """Test execution with 'true' command (exit code 0)."""
    task_data = {
        "name": "true-task",
        "command": "true",
        "shell": "/bin/sh",
    }
    create_response = client.post("/api/tasks", json=task_data)
    assert create_response.status_code == 201
    task_id = create_response.json()["id"]

    response = client.post(f"/api/tasks/{task_id}/execute")
    assert response.status_code == 202
    run_id = response.json()["id"]

    test_session_factory = sessionmaker(bind=test_engine)
    session = test_session_factory()
    run = session.query(Run).filter(Run.id == run_id).first()
    session.close()
    assert run is not None
    assert run.status == RunStatus.SUCCESS
    assert run.exit_code == 0


def test_execute_task_with_false_command(client: TestClient, test_engine: Engine) -> None:
    """Test execution with 'false' command (exit code 1)."""
    task_data = {
        "name": "false-task",
        "command": "false",
        "shell": "/bin/sh",
    }
    create_response = client.post("/api/tasks", json=task_data)
    assert create_response.status_code == 201
    task_id = create_response.json()["id"]

    response = client.post(f"/api/tasks/{task_id}/execute")
    assert response.status_code == 202
    run_id = response.json()["id"]

    test_session_factory = sessionmaker(bind=test_engine)
    session = test_session_factory()
    run = session.query(Run).filter(Run.id == run_id).first()
    session.close()
    assert run is not None
    assert run.status == RunStatus.FAILED
    assert run.exit_code == 1
