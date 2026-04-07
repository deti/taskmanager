"""Domain exceptions for the task management system.

This module defines custom exceptions used throughout the application
to handle domain-specific error conditions.
"""


class TaskNotFoundError(Exception):
    """Raised when a task lookup by ID fails.

    This exception is raised by the service layer when attempting to
    retrieve, update, or delete a task that does not exist in the database.

    Attributes:
        task_id: The ID of the task that was not found.
        message: Formatted error message.
    """

    def __init__(self, task_id: int) -> None:
        """Initialize the exception.

        Args:
            task_id: The ID of the task that was not found.
        """
        self.task_id = task_id
        self.message = f"Task with ID {task_id} not found"
        super().__init__(self.message)


class DuplicateTaskError(ValueError):
    """Raised when attempting to create a task with a duplicate name.

    This exception is raised by the service layer when trying to create
    a new task with a name that already exists in the database.

    Attributes:
        name: The duplicate task name.
        message: Formatted error message.
    """

    def __init__(self, name: str) -> None:
        """Initialize the exception.

        Args:
            name: The duplicate task name.
        """
        self.name = name
        self.message = f"Task with name '{name}' already exists"
        super().__init__(self.message)
