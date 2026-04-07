"""Pydantic schemas for API request/response models.

This module defines all request and response schemas used by the API endpoints.
Schemas handle validation, serialization, and ORM model conversion.
"""

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from taskmanager.models import RunStatus


class TaskCreate(BaseModel):
    """Schema for creating a new task."""

    name: str = Field(..., min_length=1, max_length=255, description="Unique task name")
    command: str = Field(..., min_length=1, description="Command to execute")
    description: str | None = Field(None, description="Optional task description")
    shell: str = Field(
        default="/bin/sh",
        min_length=1,
        max_length=255,
        description="Shell to use for execution",
    )

    @field_validator("name")
    @classmethod
    def validate_name_not_empty(cls, v: str) -> str:
        """Ensure name is not just whitespace."""
        if not v.strip():
            msg = "Task name cannot be empty or whitespace"
            raise ValueError(msg)
        return v.strip()

    @field_validator("command")
    @classmethod
    def validate_command_not_empty(cls, v: str) -> str:
        """Ensure command is not just whitespace."""
        if not v.strip():
            msg = "Command cannot be empty or whitespace"
            raise ValueError(msg)
        return v.strip()


class TaskUpdate(BaseModel):
    """Schema for updating an existing task.

    All fields are optional to support partial updates.
    """

    name: str | None = Field(None, min_length=1, max_length=255, description="New task name")
    command: str | None = Field(None, min_length=1, description="New command to execute")
    description: str | None = Field(None, description="New task description")
    shell: str | None = Field(
        None,
        min_length=1,
        max_length=255,
        description="New shell to use for execution",
    )

    @field_validator("name")
    @classmethod
    def validate_name_not_empty(cls, v: str | None) -> str | None:
        """Ensure name is not just whitespace if provided."""
        if v is not None and not v.strip():
            msg = "Task name cannot be empty or whitespace"
            raise ValueError(msg)
        return v.strip() if v is not None else None

    @field_validator("command")
    @classmethod
    def validate_command_not_empty(cls, v: str | None) -> str | None:
        """Ensure command is not just whitespace if provided."""
        if v is not None and not v.strip():
            msg = "Command cannot be empty or whitespace"
            raise ValueError(msg)
        return v.strip() if v is not None else None


class TaskResponse(BaseModel):
    """Schema for task response data."""

    id: str = Field(..., description="Unique task identifier (UUID)")
    name: str = Field(..., description="Task name")
    command: str = Field(..., description="Command to execute")
    description: str | None = Field(None, description="Task description")
    shell: str = Field(..., description="Shell used for execution")
    created_at: datetime = Field(..., description="Task creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = ConfigDict(from_attributes=True)


class RunResponse(BaseModel):
    """Schema for task run response data."""

    id: str = Field(..., description="Unique run identifier (UUID)")
    task_id: str | None = Field(None, description="Associated task ID (null for inline runs)")
    status: RunStatus = Field(..., description="Current run status")
    exit_code: int | None = Field(None, description="Process exit code")
    stdout: str = Field(default="", description="Standard output")
    stderr: str = Field(default="", description="Standard error")
    started_at: datetime | None = Field(None, description="Run start timestamp")
    finished_at: datetime | None = Field(None, description="Run completion timestamp")
    duration_ms: int | None = Field(None, description="Execution duration in milliseconds")

    model_config = ConfigDict(from_attributes=True)


T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):  # noqa: UP046
    """Generic paginated response wrapper.

    Wraps a list of items with pagination metadata.

    Type Parameters:
        T: The type of items in the response (e.g., TaskResponse, RunResponse)

    Example:
        PaginatedResponse[TaskResponse](
            items=[task1, task2],
            total=100,
            page=1,
            page_size=20
        )
    """

    items: list[T] = Field(..., description="List of items for current page")
    total: int = Field(..., ge=0, description="Total number of items across all pages")
    page: int = Field(..., ge=1, description="Current page number (1-indexed)")
    page_size: int = Field(..., ge=1, description="Number of items per page")

    model_config = ConfigDict(from_attributes=True)
