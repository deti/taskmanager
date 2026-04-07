"""ORM models for taskmanager."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from taskmanager.database import Base


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
