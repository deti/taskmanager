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

    def __init__(self, task_id: int | str) -> None:
        """Initialize the exception.

        Args:
            task_id: The ID of the task that was not found (int or UUID string).
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


class RunNotFoundError(Exception):
    """Raised when a run lookup by ID fails.

    This exception is raised by the service layer when attempting to
    retrieve a run that does not exist in the database.

    Attributes:
        run_id: The ID of the run that was not found.
        message: Formatted error message.
    """

    def __init__(self, run_id: str) -> None:
        """Initialize the exception.

        Args:
            run_id: The ID of the run that was not found (UUID string).
        """
        self.run_id = run_id
        self.message = f"Run with ID {run_id} not found"
        super().__init__(self.message)


class ScheduleNotFoundError(Exception):
    """Raised when a schedule lookup by ID fails.

    This exception is raised by the service layer when attempting to
    retrieve, update, or delete a schedule that does not exist in the database.

    Attributes:
        schedule_id: The ID of the schedule that was not found.
        message: Formatted error message.
    """

    def __init__(self, schedule_id: str) -> None:
        """Initialize the exception.

        Args:
            schedule_id: The ID of the schedule that was not found (UUID string).
        """
        self.schedule_id = schedule_id
        self.message = f"Schedule with ID {schedule_id} not found"
        super().__init__(self.message)


class DuplicateScheduleError(ValueError):
    """Raised when attempting to create a schedule with duplicate task_id + trigger_type.

    This exception is raised by the service layer when trying to create
    a new schedule for a task that already has a schedule of the same trigger type.

    Attributes:
        task_id: The task ID.
        trigger_type: The trigger type.
        message: Formatted error message.
    """

    def __init__(self, task_id: str, trigger_type: object) -> None:
        """Initialize the exception.

        Args:
            task_id: The task ID.
            trigger_type: The trigger type enum.
        """
        self.task_id = task_id
        self.trigger_type = trigger_type
        # Handle enum by accessing .value attribute
        trigger_value = getattr(trigger_type, "value", str(trigger_type))
        self.message = (
            f"Schedule with task_id '{task_id}' and trigger_type '{trigger_value}' "
            "already exists"
        )
        super().__init__(self.message)


class ScheduleValidationError(ValueError):
    """Raised when schedule trigger configuration is invalid.

    This exception is raised by the service layer when the trigger_config
    JSON does not match the expected schema for the trigger type.

    Attributes:
        message: Formatted error message.
    """

    def __init__(self, message: str) -> None:
        """Initialize the exception.

        Args:
            message: Description of the validation error.
        """
        self.message = message
        super().__init__(self.message)
