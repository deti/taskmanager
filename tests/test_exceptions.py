"""Tests for domain exceptions."""

import pytest

from taskmanager.exceptions import DuplicateTaskError, TaskNotFoundError


class TestTaskNotFoundError:
    """Tests for TaskNotFoundError exception."""

    def test_exception_message_format(self) -> None:
        """Test that the error message is formatted correctly."""
        task_id = 42
        error = TaskNotFoundError(task_id)

        assert error.task_id == task_id
        assert error.message == "Task with ID 42 not found"
        assert str(error) == "Task with ID 42 not found"

    def test_inherits_from_exception(self) -> None:
        """Test that TaskNotFoundError inherits from Exception."""
        error = TaskNotFoundError(1)
        assert isinstance(error, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        """Test that the exception can be raised and caught."""
        with pytest.raises(TaskNotFoundError) as exc_info:
            raise TaskNotFoundError(99)

        assert exc_info.value.task_id == 99
        assert "Task with ID 99 not found" in str(exc_info.value)


class TestDuplicateTaskError:
    """Tests for DuplicateTaskError exception."""

    def test_exception_message_format(self) -> None:
        """Test that the error message is formatted correctly."""
        task_name = "My Task"
        error = DuplicateTaskError(task_name)

        assert error.name == task_name
        assert error.message == "Task with name 'My Task' already exists"
        assert str(error) == "Task with name 'My Task' already exists"

    def test_inherits_from_value_error(self) -> None:
        """Test that DuplicateTaskError inherits from ValueError."""
        error = DuplicateTaskError("test")
        assert isinstance(error, ValueError)
        assert isinstance(error, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        """Test that the exception can be raised and caught."""
        with pytest.raises(DuplicateTaskError) as exc_info:
            raise DuplicateTaskError("Duplicate Task")  # noqa: TRY003

        assert exc_info.value.name == "Duplicate Task"
        assert "Task with name 'Duplicate Task' already exists" in str(exc_info.value)

    def test_handles_special_characters_in_name(self) -> None:
        """Test that special characters in task names are handled correctly."""
        special_name = "Task's \"Special\" Name & More"
        error = DuplicateTaskError(special_name)

        assert error.name == special_name
        assert f"Task with name '{special_name}' already exists" == error.message
