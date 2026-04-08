"""Tests for Schedule CRUD API endpoints.

This module tests all schedule-related API endpoints including full CRUD operations,
enable/disable functionality, and filtering.
"""

import json
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
from taskmanager.models import Schedule, Task, TriggerType


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
def another_task(test_session: Session) -> Task:
    """Create another task for testing.

    Args:
        test_session: Test database session.

    Returns:
        Task: A created task instance.
    """
    task = Task(
        name="another-task",
        command="echo 'another'",
        description="Another task for testing",
        shell="/bin/sh",
    )
    test_session.add(task)
    test_session.commit()
    test_session.refresh(task)
    return task


@pytest.fixture
def sample_schedules(test_session: Session, sample_task: Task, another_task: Task) -> list[Schedule]:
    """Create sample schedules for testing.

    Creates schedules in different states for comprehensive testing.

    Args:
        test_session: Test database session.
        sample_task: Sample task fixture.
        another_task: Another task fixture.

    Returns:
        list[Schedule]: List of created schedule instances.
    """
    schedules = [
        Schedule(
            task_id=sample_task.id,
            trigger_type=TriggerType.CRON,
            trigger_config=json.dumps({"cron": "0 2 * * *"}),
            enabled=True,
        ),
        Schedule(
            task_id=sample_task.id,
            trigger_type=TriggerType.INTERVAL,
            trigger_config=json.dumps({"interval": {"seconds": 3600}}),
            enabled=False,
        ),
        Schedule(
            task_id=another_task.id,
            trigger_type=TriggerType.ONCE,
            trigger_config=json.dumps({"once": "2026-04-09T10:00:00Z"}),
            enabled=True,
        ),
    ]

    for schedule in schedules:
        test_session.add(schedule)
    test_session.commit()

    for schedule in schedules:
        test_session.refresh(schedule)

    return schedules


# ============================================================================
# Create Schedule Tests (Task 2.2)
# ============================================================================


def test_create_schedule_success(client: TestClient, sample_task: Task) -> None:
    """Test POST /api/schedules creates schedule successfully."""
    schedule_data = {
        "task_id": sample_task.id,
        "trigger_type": "cron",
        "trigger_config": {"cron": "0 3 * * *"},
        "enabled": True,
    }

    response = client.post("/api/schedules", json=schedule_data)

    assert response.status_code == 201
    json_data = response.json()
    assert json_data["task_id"] == sample_task.id
    assert json_data["trigger_type"] == "cron"
    assert json_data["trigger_config"] == {"cron": "0 3 * * *"}
    assert json_data["enabled"] is True
    assert "id" in json_data
    assert "created_at" in json_data
    assert "updated_at" in json_data


def test_create_schedule_default_enabled(client: TestClient, sample_task: Task) -> None:
    """Test POST /api/schedules defaults enabled to True when not provided."""
    schedule_data = {
        "task_id": sample_task.id,
        "trigger_type": "interval",
        "trigger_config": {"interval": {"seconds": 60}},
    }

    response = client.post("/api/schedules", json=schedule_data)

    assert response.status_code == 201
    json_data = response.json()
    assert json_data["enabled"] is True


def test_create_schedule_interval_trigger(client: TestClient, sample_task: Task) -> None:
    """Test POST /api/schedules with interval trigger type."""
    schedule_data = {
        "task_id": sample_task.id,
        "trigger_type": "interval",
        "trigger_config": {"interval": {"seconds": 3600}},
        "enabled": False,
    }

    response = client.post("/api/schedules", json=schedule_data)

    assert response.status_code == 201
    json_data = response.json()
    assert json_data["trigger_type"] == "interval"
    assert json_data["trigger_config"] == {"interval": {"seconds": 3600}}
    assert json_data["enabled"] is False


def test_create_schedule_once_trigger(client: TestClient, sample_task: Task) -> None:
    """Test POST /api/schedules with once trigger type."""
    schedule_data = {
        "task_id": sample_task.id,
        "trigger_type": "once",
        "trigger_config": {"once": "2026-04-10T15:30:00Z"},
        "enabled": True,
    }

    response = client.post("/api/schedules", json=schedule_data)

    assert response.status_code == 201
    json_data = response.json()
    assert json_data["trigger_type"] == "once"
    assert json_data["trigger_config"] == {"once": "2026-04-10T15:30:00Z"}


def test_create_schedule_nonexistent_task_returns_404(client: TestClient) -> None:
    """Test POST /api/schedules with nonexistent task returns 404."""
    fake_uuid = "123e4567-e89b-12d3-a456-426614174000"
    schedule_data = {
        "task_id": fake_uuid,
        "trigger_type": "cron",
        "trigger_config": {"cron": "0 2 * * *"},
    }

    response = client.post("/api/schedules", json=schedule_data)

    assert response.status_code == 404
    json_data = response.json()
    assert json_data["error"] == "Not Found"
    assert fake_uuid in json_data["message"]


def test_create_schedule_duplicate_returns_409(
    client: TestClient, sample_task: Task, sample_schedules: list[Schedule]
) -> None:
    """Test POST /api/schedules with duplicate task+trigger_type returns 409."""
    # sample_schedules already has a CRON schedule for sample_task
    duplicate_data = {
        "task_id": sample_task.id,
        "trigger_type": "cron",
        "trigger_config": {"cron": "0 5 * * *"},  # Different config, but same task+type
    }

    response = client.post("/api/schedules", json=duplicate_data)

    assert response.status_code == 409
    json_data = response.json()
    assert json_data["error"] == "Conflict"
    assert "already exists" in json_data["message"].lower()


def test_create_schedule_invalid_trigger_config_returns_422(
    client: TestClient, sample_task: Task
) -> None:
    """Test POST /api/schedules with invalid trigger_config returns 422."""
    # Invalid cron expression
    schedule_data = {
        "task_id": sample_task.id,
        "trigger_type": "cron",
        "trigger_config": {"cron": "invalid cron"},
    }

    response = client.post("/api/schedules", json=schedule_data)

    assert response.status_code == 422
    json_data = response.json()
    assert json_data["error"] == "Unprocessable Entity"


# ============================================================================
# List Schedules Tests (Task 2.2)
# ============================================================================


def test_list_schedules_empty(client: TestClient) -> None:
    """Test GET /api/schedules returns empty list when no schedules exist."""
    response = client.get("/api/schedules")

    assert response.status_code == 200
    json_data = response.json()
    assert json_data == []


def test_list_schedules_all(client: TestClient, sample_schedules: list[Schedule]) -> None:
    """Test GET /api/schedules returns all schedules."""
    response = client.get("/api/schedules")

    assert response.status_code == 200
    json_data = response.json()
    assert len(json_data) == 3

    # Verify schedule IDs match
    schedule_ids = {s["id"] for s in json_data}
    expected_ids = {s.id for s in sample_schedules}
    assert schedule_ids == expected_ids


def test_list_schedules_filter_by_task_id(
    client: TestClient, sample_task: Task, sample_schedules: list[Schedule]
) -> None:
    """Test GET /api/schedules?task_id=X filters by task ID."""
    response = client.get(f"/api/schedules?task_id={sample_task.id}")

    assert response.status_code == 200
    json_data = response.json()
    assert len(json_data) == 2  # sample_task has 2 schedules (CRON and INTERVAL)

    # Verify all returned schedules belong to sample_task
    for schedule_data in json_data:
        assert schedule_data["task_id"] == sample_task.id


def test_list_schedules_filter_by_enabled_true(
    client: TestClient, sample_schedules: list[Schedule]
) -> None:
    """Test GET /api/schedules?enabled=true filters by enabled status."""
    response = client.get("/api/schedules?enabled=true")

    assert response.status_code == 200
    json_data = response.json()
    assert len(json_data) == 2  # 2 enabled schedules

    # Verify all returned schedules are enabled
    for schedule_data in json_data:
        assert schedule_data["enabled"] is True


def test_list_schedules_filter_by_enabled_false(
    client: TestClient, sample_schedules: list[Schedule]
) -> None:
    """Test GET /api/schedules?enabled=false filters by disabled status."""
    response = client.get("/api/schedules?enabled=false")

    assert response.status_code == 200
    json_data = response.json()
    assert len(json_data) == 1  # 1 disabled schedule

    # Verify all returned schedules are disabled
    for schedule_data in json_data:
        assert schedule_data["enabled"] is False


def test_list_schedules_combined_filters(
    client: TestClient, sample_task: Task, sample_schedules: list[Schedule]
) -> None:
    """Test GET /api/schedules with multiple filters combined."""
    response = client.get(f"/api/schedules?task_id={sample_task.id}&enabled=true")

    assert response.status_code == 200
    json_data = response.json()
    assert len(json_data) == 1  # Only 1 enabled schedule for sample_task

    assert json_data[0]["task_id"] == sample_task.id
    assert json_data[0]["enabled"] is True


# ============================================================================
# Get Schedule Tests (Task 2.2)
# ============================================================================


def test_get_schedule_by_id_success(
    client: TestClient, sample_schedules: list[Schedule]
) -> None:
    """Test GET /api/schedules/{id} returns schedule details."""
    schedule = sample_schedules[0]
    response = client.get(f"/api/schedules/{schedule.id}")

    assert response.status_code == 200
    json_data = response.json()
    assert json_data["id"] == schedule.id
    assert json_data["task_id"] == schedule.task_id
    assert json_data["trigger_type"] == schedule.trigger_type.value
    assert json_data["trigger_config"] == {"cron": "0 2 * * *"}
    assert json_data["enabled"] == schedule.enabled


def test_get_schedule_invalid_id_returns_404(client: TestClient) -> None:
    """Test GET /api/schedules/{id} with invalid ID returns 404."""
    fake_uuid = "123e4567-e89b-12d3-a456-426614174000"

    response = client.get(f"/api/schedules/{fake_uuid}")

    assert response.status_code == 404
    json_data = response.json()
    assert json_data["error"] == "Not Found"
    assert fake_uuid in json_data["message"]


def test_get_schedule_all_fields_populated(
    client: TestClient, sample_schedules: list[Schedule]
) -> None:
    """Test GET /api/schedules/{id} returns all expected fields."""
    schedule = sample_schedules[0]
    response = client.get(f"/api/schedules/{schedule.id}")

    assert response.status_code == 200
    json_data = response.json()

    # Verify all expected fields are present
    required_fields = [
        "id",
        "task_id",
        "trigger_type",
        "trigger_config",
        "enabled",
        "last_run_at",
        "next_run_at",
        "created_at",
        "updated_at",
    ]
    for field in required_fields:
        assert field in json_data


# ============================================================================
# Update Schedule Tests (Task 2.2)
# ============================================================================


def test_update_schedule_trigger_config(
    client: TestClient, sample_schedules: list[Schedule]
) -> None:
    """Test PUT /api/schedules/{id} updates trigger_config."""
    schedule = sample_schedules[0]
    update_data = {
        "trigger_config": {"cron": "0 4 * * *"},
    }

    response = client.put(f"/api/schedules/{schedule.id}", json=update_data)

    assert response.status_code == 200
    json_data = response.json()
    assert json_data["id"] == schedule.id
    assert json_data["trigger_config"] == {"cron": "0 4 * * *"}
    assert json_data["enabled"] == schedule.enabled  # Unchanged


def test_update_schedule_enabled_flag(
    client: TestClient, sample_schedules: list[Schedule]
) -> None:
    """Test PUT /api/schedules/{id} updates enabled flag."""
    schedule = sample_schedules[0]
    update_data = {
        "enabled": False,
    }

    response = client.put(f"/api/schedules/{schedule.id}", json=update_data)

    assert response.status_code == 200
    json_data = response.json()
    assert json_data["id"] == schedule.id
    assert json_data["enabled"] is False
    # trigger_config should remain unchanged
    assert json_data["trigger_config"] == {"cron": "0 2 * * *"}


def test_update_schedule_both_fields(
    client: TestClient, sample_schedules: list[Schedule]
) -> None:
    """Test PUT /api/schedules/{id} updates both trigger_config and enabled."""
    schedule = sample_schedules[0]
    update_data = {
        "trigger_config": {"cron": "0 6 * * *"},
        "enabled": False,
    }

    response = client.put(f"/api/schedules/{schedule.id}", json=update_data)

    assert response.status_code == 200
    json_data = response.json()
    assert json_data["id"] == schedule.id
    assert json_data["trigger_config"] == {"cron": "0 6 * * *"}
    assert json_data["enabled"] is False


def test_update_schedule_invalid_id_returns_404(client: TestClient) -> None:
    """Test PUT /api/schedules/{id} with invalid ID returns 404."""
    fake_uuid = "123e4567-e89b-12d3-a456-426614174000"
    update_data = {
        "enabled": False,
    }

    response = client.put(f"/api/schedules/{fake_uuid}", json=update_data)

    assert response.status_code == 404
    json_data = response.json()
    assert json_data["error"] == "Not Found"
    assert fake_uuid in json_data["message"]


def test_update_schedule_invalid_trigger_config_returns_422(
    client: TestClient, sample_schedules: list[Schedule]
) -> None:
    """Test PUT /api/schedules/{id} with invalid trigger_config returns 422."""
    schedule = sample_schedules[0]
    update_data = {
        "trigger_config": {"cron": "invalid"},
    }

    response = client.put(f"/api/schedules/{schedule.id}", json=update_data)

    assert response.status_code == 422
    json_data = response.json()
    assert json_data["error"] == "Unprocessable Entity"


# ============================================================================
# Delete Schedule Tests (Task 2.2)
# ============================================================================


def test_delete_schedule_success(
    client: TestClient, sample_schedules: list[Schedule]
) -> None:
    """Test DELETE /api/schedules/{id} removes schedule."""
    schedule = sample_schedules[0]
    response = client.delete(f"/api/schedules/{schedule.id}")

    assert response.status_code == 204

    # Verify schedule is deleted
    get_response = client.get(f"/api/schedules/{schedule.id}")
    assert get_response.status_code == 404


def test_delete_schedule_invalid_id_returns_404(client: TestClient) -> None:
    """Test DELETE /api/schedules/{id} with invalid ID returns 404."""
    fake_uuid = "123e4567-e89b-12d3-a456-426614174000"

    response = client.delete(f"/api/schedules/{fake_uuid}")

    assert response.status_code == 404
    json_data = response.json()
    assert json_data["error"] == "Not Found"
    assert fake_uuid in json_data["message"]


# ============================================================================
# Enable Schedule Tests (Task 2.2)
# ============================================================================


def test_enable_schedule_success(
    client: TestClient, sample_schedules: list[Schedule]
) -> None:
    """Test POST /api/schedules/{id}/enable sets enabled=True."""
    # Use the disabled schedule (index 1)
    schedule = sample_schedules[1]
    assert schedule.enabled is False  # Verify it starts disabled

    response = client.post(f"/api/schedules/{schedule.id}/enable")

    assert response.status_code == 200
    json_data = response.json()
    assert json_data["id"] == schedule.id
    assert json_data["enabled"] is True

    # Verify via GET
    get_response = client.get(f"/api/schedules/{schedule.id}")
    assert get_response.status_code == 200
    assert get_response.json()["enabled"] is True


def test_enable_schedule_already_enabled(
    client: TestClient, sample_schedules: list[Schedule]
) -> None:
    """Test POST /api/schedules/{id}/enable on already enabled schedule."""
    # Use an already enabled schedule (index 0)
    schedule = sample_schedules[0]
    assert schedule.enabled is True

    response = client.post(f"/api/schedules/{schedule.id}/enable")

    assert response.status_code == 200
    json_data = response.json()
    assert json_data["enabled"] is True  # Should remain True


def test_enable_schedule_invalid_id_returns_404(client: TestClient) -> None:
    """Test POST /api/schedules/{id}/enable with invalid ID returns 404."""
    fake_uuid = "123e4567-e89b-12d3-a456-426614174000"

    response = client.post(f"/api/schedules/{fake_uuid}/enable")

    assert response.status_code == 404
    json_data = response.json()
    assert json_data["error"] == "Not Found"
    assert fake_uuid in json_data["message"]


# ============================================================================
# Disable Schedule Tests (Task 2.2)
# ============================================================================


def test_disable_schedule_success(
    client: TestClient, sample_schedules: list[Schedule]
) -> None:
    """Test POST /api/schedules/{id}/disable sets enabled=False."""
    # Use an enabled schedule (index 0)
    schedule = sample_schedules[0]
    assert schedule.enabled is True  # Verify it starts enabled

    response = client.post(f"/api/schedules/{schedule.id}/disable")

    assert response.status_code == 200
    json_data = response.json()
    assert json_data["id"] == schedule.id
    assert json_data["enabled"] is False

    # Verify via GET
    get_response = client.get(f"/api/schedules/{schedule.id}")
    assert get_response.status_code == 200
    assert get_response.json()["enabled"] is False


def test_disable_schedule_already_disabled(
    client: TestClient, sample_schedules: list[Schedule]
) -> None:
    """Test POST /api/schedules/{id}/disable on already disabled schedule."""
    # Use the disabled schedule (index 1)
    schedule = sample_schedules[1]
    assert schedule.enabled is False

    response = client.post(f"/api/schedules/{schedule.id}/disable")

    assert response.status_code == 200
    json_data = response.json()
    assert json_data["enabled"] is False  # Should remain False


def test_disable_schedule_invalid_id_returns_404(client: TestClient) -> None:
    """Test POST /api/schedules/{id}/disable with invalid ID returns 404."""
    fake_uuid = "123e4567-e89b-12d3-a456-426614174000"

    response = client.post(f"/api/schedules/{fake_uuid}/disable")

    assert response.status_code == 404
    json_data = response.json()
    assert json_data["error"] == "Not Found"
    assert fake_uuid in json_data["message"]


# ============================================================================
# Edge Cases and Error Handling (Task 2.2)
# ============================================================================


def test_schedule_trigger_config_json_parsing(
    client: TestClient, sample_schedules: list[Schedule]
) -> None:
    """Test that trigger_config is properly parsed from JSON string to dict."""
    schedule = sample_schedules[0]
    response = client.get(f"/api/schedules/{schedule.id}")

    assert response.status_code == 200
    json_data = response.json()

    # Verify trigger_config is a dict, not a string
    assert isinstance(json_data["trigger_config"], dict)
    assert json_data["trigger_config"] == {"cron": "0 2 * * *"}


def test_schedule_response_format(
    client: TestClient, sample_task: Task
) -> None:
    """Test that schedule response format matches expected schema."""
    schedule_data = {
        "task_id": sample_task.id,
        "trigger_type": "cron",
        "trigger_config": {"cron": "0 1 * * *"},
        "enabled": True,
    }

    response = client.post("/api/schedules", json=schedule_data)

    assert response.status_code == 201
    json_data = response.json()

    # Verify response structure matches ScheduleResponse schema
    assert isinstance(json_data["id"], str)
    assert isinstance(json_data["task_id"], str)
    assert isinstance(json_data["trigger_type"], str)
    assert isinstance(json_data["trigger_config"], dict)
    assert isinstance(json_data["enabled"], bool)
    assert isinstance(json_data["created_at"], str)
    assert isinstance(json_data["updated_at"], str)


def test_create_schedule_empty_trigger_config_returns_422(
    client: TestClient, sample_task: Task
) -> None:
    """Test POST /api/schedules with empty trigger_config returns 422."""
    schedule_data = {
        "task_id": sample_task.id,
        "trigger_type": "cron",
        "trigger_config": {},  # Empty config
    }

    response = client.post("/api/schedules", json=schedule_data)

    assert response.status_code == 422
    json_data = response.json()
    assert json_data["error"] == "Unprocessable Entity"
