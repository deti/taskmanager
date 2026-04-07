"""Tests for API Pydantic schemas."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from taskmanager.api.schemas import (
    PaginatedResponse,
    RunResponse,
    TaskCreate,
    TaskResponse,
    TaskUpdate,
)
from taskmanager.models import RunStatus, Task


class TestTaskCreate:
    """Tests for TaskCreate schema."""

    def test_valid_task_create(self) -> None:
        """Test creating a valid TaskCreate instance."""
        task = TaskCreate(
            name="backup",
            command="tar -czf backup.tar.gz /data",
            description="Daily backup",
            shell="/bin/bash",
        )

        assert task.name == "backup"
        assert task.command == "tar -czf backup.tar.gz /data"
        assert task.description == "Daily backup"
        assert task.shell == "/bin/bash"

    def test_task_create_default_shell(self) -> None:
        """Test that shell defaults to /bin/sh."""
        task = TaskCreate(name="test", command="echo hello")

        assert task.shell == "/bin/sh"

    def test_task_create_strips_whitespace_from_name(self) -> None:
        """Test that name whitespace is stripped."""
        task = TaskCreate(name="  test  ", command="echo hello")

        assert task.name == "test"

    def test_task_create_strips_whitespace_from_command(self) -> None:
        """Test that command whitespace is stripped."""
        task = TaskCreate(name="test", command="  echo hello  ")

        assert task.command == "echo hello"

    def test_task_create_empty_name_fails(self) -> None:
        """Test that empty name fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            TaskCreate(name="", command="echo hello")

        errors = exc_info.value.errors()
        assert any("name" in str(e) for e in errors)

    def test_task_create_whitespace_only_name_fails(self) -> None:
        """Test that whitespace-only name fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            TaskCreate(name="   ", command="echo hello")

        errors = exc_info.value.errors()
        assert any("whitespace" in str(e).lower() for e in errors)

    def test_task_create_empty_command_fails(self) -> None:
        """Test that empty command fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            TaskCreate(name="test", command="")

        errors = exc_info.value.errors()
        assert any("command" in str(e) for e in errors)

    def test_task_create_whitespace_only_command_fails(self) -> None:
        """Test that whitespace-only command fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            TaskCreate(name="test", command="   ")

        errors = exc_info.value.errors()
        assert any("whitespace" in str(e).lower() for e in errors)

    def test_task_create_name_too_long_fails(self) -> None:
        """Test that name exceeding max length fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            TaskCreate(name="a" * 256, command="echo hello")

        errors = exc_info.value.errors()
        assert any("name" in str(e) for e in errors)


class TestTaskUpdate:
    """Tests for TaskUpdate schema."""

    def test_valid_task_update_all_fields(self) -> None:
        """Test updating all fields."""
        update = TaskUpdate(
            name="new-name",
            command="new command",
            description="new description",
            shell="/bin/zsh",
        )

        assert update.name == "new-name"
        assert update.command == "new command"
        assert update.description == "new description"
        assert update.shell == "/bin/zsh"

    def test_task_update_partial(self) -> None:
        """Test partial update with only some fields."""
        update = TaskUpdate(name="new-name")

        assert update.name == "new-name"
        assert update.command is None
        assert update.description is None
        assert update.shell is None

    def test_task_update_strips_whitespace_from_name(self) -> None:
        """Test that name whitespace is stripped."""
        update = TaskUpdate(name="  new-name  ")

        assert update.name == "new-name"

    def test_task_update_strips_whitespace_from_command(self) -> None:
        """Test that command whitespace is stripped."""
        update = TaskUpdate(command="  new command  ")

        assert update.command == "new command"

    def test_task_update_whitespace_only_name_fails(self) -> None:
        """Test that whitespace-only name fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            TaskUpdate(name="   ")

        errors = exc_info.value.errors()
        assert any("whitespace" in str(e).lower() for e in errors)

    def test_task_update_whitespace_only_command_fails(self) -> None:
        """Test that whitespace-only command fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            TaskUpdate(command="   ")

        errors = exc_info.value.errors()
        assert any("whitespace" in str(e).lower() for e in errors)


class TestTaskResponse:
    """Tests for TaskResponse schema."""

    def test_task_response_from_orm_model(self) -> None:
        """Test creating TaskResponse from ORM Task model."""
        task = Task(
            id="test-id",
            name="test-task",
            command="echo hello",
            description="Test description",
            shell="/bin/bash",
            created_at=datetime(2024, 1, 1, 12, 0, 0),
            updated_at=datetime(2024, 1, 1, 12, 0, 0),
        )

        response = TaskResponse.model_validate(task)

        assert response.id == "test-id"
        assert response.name == "test-task"
        assert response.command == "echo hello"
        assert response.description == "Test description"
        assert response.shell == "/bin/bash"
        assert response.created_at == datetime(2024, 1, 1, 12, 0, 0)
        assert response.updated_at == datetime(2024, 1, 1, 12, 0, 0)

    def test_task_response_serialization(self) -> None:
        """Test that TaskResponse can be serialized to dict."""
        response = TaskResponse(
            id="test-id",
            name="test-task",
            command="echo hello",
            description="Test",
            shell="/bin/bash",
            created_at=datetime(2024, 1, 1, 12, 0, 0),
            updated_at=datetime(2024, 1, 1, 12, 0, 0),
        )

        data = response.model_dump()

        assert data["id"] == "test-id"
        assert data["name"] == "test-task"
        assert data["command"] == "echo hello"


class TestRunResponse:
    """Tests for RunResponse schema."""

    def test_run_response_all_fields(self) -> None:
        """Test creating RunResponse with all fields."""
        response = RunResponse(
            id="run-id",
            task_id="task-id",
            status=RunStatus.SUCCESS,
            exit_code=0,
            stdout="output",
            stderr="",
            started_at=datetime(2024, 1, 1, 12, 0, 0),
            finished_at=datetime(2024, 1, 1, 12, 0, 5),
            duration_ms=5000,
        )

        assert response.id == "run-id"
        assert response.task_id == "task-id"
        assert response.status == RunStatus.SUCCESS
        assert response.exit_code == 0
        assert response.stdout == "output"
        assert response.stderr == ""
        assert response.duration_ms == 5000

    def test_run_response_defaults(self) -> None:
        """Test RunResponse defaults for optional fields."""
        response = RunResponse(
            id="run-id",
            status=RunStatus.PENDING,
        )

        assert response.task_id is None
        assert response.exit_code is None
        assert response.stdout == ""
        assert response.stderr == ""
        assert response.started_at is None
        assert response.finished_at is None
        assert response.duration_ms is None


class TestPaginatedResponse:
    """Tests for PaginatedResponse schema."""

    def test_paginated_response_with_tasks(self) -> None:
        """Test PaginatedResponse with TaskResponse items."""
        tasks = [
            TaskResponse(
                id="1",
                name="task1",
                command="echo 1",
                description=None,
                shell="/bin/sh",
                created_at=datetime(2024, 1, 1),
                updated_at=datetime(2024, 1, 1),
            ),
            TaskResponse(
                id="2",
                name="task2",
                command="echo 2",
                description=None,
                shell="/bin/sh",
                created_at=datetime(2024, 1, 2),
                updated_at=datetime(2024, 1, 2),
            ),
        ]

        response = PaginatedResponse[TaskResponse](
            items=tasks,
            total=100,
            page=1,
            page_size=20,
        )

        assert len(response.items) == 2
        assert response.total == 100
        assert response.page == 1
        assert response.page_size == 20

    def test_paginated_response_with_runs(self) -> None:
        """Test PaginatedResponse with RunResponse items."""
        runs = [
            RunResponse(id="1", status=RunStatus.SUCCESS),
            RunResponse(id="2", status=RunStatus.FAILED),
        ]

        response = PaginatedResponse[RunResponse](
            items=runs,
            total=50,
            page=2,
            page_size=10,
        )

        assert len(response.items) == 2
        assert response.total == 50
        assert response.page == 2
        assert response.page_size == 10

    def test_paginated_response_empty_items(self) -> None:
        """Test PaginatedResponse with empty items list."""
        response = PaginatedResponse[TaskResponse](
            items=[],
            total=0,
            page=1,
            page_size=20,
        )

        assert response.items == []
        assert response.total == 0

    def test_paginated_response_invalid_total(self) -> None:
        """Test that negative total fails validation."""
        with pytest.raises(ValidationError):
            PaginatedResponse[TaskResponse](
                items=[],
                total=-1,
                page=1,
                page_size=20,
            )

    def test_paginated_response_invalid_page(self) -> None:
        """Test that page < 1 fails validation."""
        with pytest.raises(ValidationError):
            PaginatedResponse[TaskResponse](
                items=[],
                total=0,
                page=0,
                page_size=20,
            )

    def test_paginated_response_invalid_page_size(self) -> None:
        """Test that page_size < 1 fails validation."""
        with pytest.raises(ValidationError):
            PaginatedResponse[TaskResponse](
                items=[],
                total=0,
                page=1,
                page_size=0,
            )
