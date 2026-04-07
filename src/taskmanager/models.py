"""ORM models for taskmanager."""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from taskmanager.database import Base


class RunStatus(enum.Enum):
    """Status of a task run."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task(Base):
    """A registered task that can be executed."""

    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("name", name="uq_task_name"),)

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    shell: Mapped[str] = mapped_column(String(255), nullable=False, default="/bin/sh")
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:
        return f"<Task(id={self.id!r}, name={self.name!r})>"


class Run(Base):
    """A single execution of a task.

    Runs can be associated with a registered task (task_id is set) or inline
    (task_id is None). Inline runs execute a command directly without requiring
    a task to be registered first.
    """

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("tasks.id"),
        nullable=True,
        default=None,
    )
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus),
        nullable=False,
        default=RunStatus.PENDING,
    )
    command_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)
    exit_code: Mapped[int | None] = mapped_column(nullable=True, default=None)
    stdout: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stderr: Mapped[str] = mapped_column(Text, nullable=False, default="")
    duration_ms: Mapped[int | None] = mapped_column(nullable=True, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    def __repr__(self) -> str:
        return f"<Run(id={self.id!r}, task_id={self.task_id!r}, status={self.status.value!r})>"
