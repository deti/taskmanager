"""Tests for API test fixtures.

These tests verify that the fixtures in conftest.py work correctly.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from taskmanager.models import Task


def test_test_db_fixture(test_db: Session) -> None:
    """Test that test_db fixture provides a working session."""
    assert test_db is not None
    assert isinstance(test_db, Session)
    assert test_db.is_active


def test_test_client_fixture(test_client: TestClient) -> None:
    """Test that test_client fixture provides a working client."""
    assert test_client is not None
    assert isinstance(test_client, TestClient)


def test_sample_task_fixture(sample_task: Task) -> None:
    """Test that sample_task fixture creates a valid task."""
    assert sample_task is not None
    assert isinstance(sample_task, Task)
    assert sample_task.id is not None
    assert sample_task.name == "test-task"
    assert sample_task.command == "echo 'Hello, World!'"
    assert sample_task.description == "A test task for unit tests"
    assert sample_task.shell == "/bin/bash"


def test_sample_task_is_persisted(sample_task: Task, test_db: Session) -> None:
    """Test that sample_task is persisted in the database."""
    # Query the database to verify the task exists
    retrieved_task = test_db.query(Task).filter_by(id=sample_task.id).first()

    assert retrieved_task is not None
    assert retrieved_task.id == sample_task.id
    assert retrieved_task.name == sample_task.name
