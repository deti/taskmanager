"""Unit tests for task service layer.

Tests all CRUD operations using in-memory SQLite database.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from taskmanager.database import Base
from taskmanager.exceptions import DuplicateTaskError, TaskNotFoundError
from taskmanager.services import (
    create_task,
    delete_task,
    get_task,
    get_task_by_name,
    list_tasks,
    update_task,
)


@pytest.fixture
def db_session() -> Session:
    """Create an in-memory SQLite session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)
    session = session_local()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class TestCreateTask:
    """Tests for create_task function."""

    def test_create_task_basic(self, db_session: Session) -> None:
        """Test creating a basic task."""
        task = create_task(
            db_session,
            name="backup",
            command="tar -czf backup.tar.gz /data",
            description="Daily backup",
        )

        assert task.id is not None
        assert task.name == "backup"
        assert task.command == "tar -czf backup.tar.gz /data"
        assert task.description == "Daily backup"
        assert task.shell == "/bin/sh"
        assert task.created_at is not None
        assert task.updated_at is not None

    def test_create_task_minimal(self, db_session: Session) -> None:
        """Test creating a task with minimal fields."""
        task = create_task(
            db_session,
            name="test",
            command="echo test",
        )

        assert task.id is not None
        assert task.name == "test"
        assert task.command == "echo test"
        assert task.description is None
        assert task.shell == "/bin/sh"

    def test_create_task_custom_shell(self, db_session: Session) -> None:
        """Test creating a task with a custom shell."""
        task = create_task(
            db_session,
            name="bash-script",
            command="echo $BASH_VERSION",
            shell="/bin/bash",
        )

        assert task.shell == "/bin/bash"

    def test_create_task_duplicate_name(self, db_session: Session) -> None:
        """Test that creating a task with duplicate name raises error."""
        create_task(db_session, name="backup", command="ls")
        db_session.commit()

        with pytest.raises(DuplicateTaskError) as exc_info:
            create_task(db_session, name="backup", command="pwd")

        assert exc_info.value.name == "backup"
        assert "already exists" in str(exc_info.value)


class TestGetTask:
    """Tests for get_task function."""

    def test_get_task_exists(self, db_session: Session) -> None:
        """Test retrieving an existing task by ID."""
        created = create_task(db_session, name="test", command="echo test")
        db_session.commit()

        retrieved = get_task(db_session, created.id)

        assert retrieved.id == created.id
        assert retrieved.name == created.name
        assert retrieved.command == created.command

    def test_get_task_not_found(self, db_session: Session) -> None:
        """Test that retrieving non-existent task raises error."""
        fake_id = "00000000-0000-0000-0000-000000000000"

        # TaskNotFoundError signature expects int but receives str (UUID)
        # Works at runtime but mypy requires type: ignore
        with pytest.raises(TaskNotFoundError) as exc_info:
            get_task(db_session, fake_id)

        assert exc_info.value.task_id == fake_id


class TestGetTaskByName:
    """Tests for get_task_by_name function."""

    def test_get_task_by_name_exists(self, db_session: Session) -> None:
        """Test retrieving an existing task by name."""
        created = create_task(db_session, name="backup", command="ls")
        db_session.commit()

        retrieved = get_task_by_name(db_session, "backup")

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.name == "backup"

    def test_get_task_by_name_not_found(self, db_session: Session) -> None:
        """Test that retrieving non-existent task returns None."""
        result = get_task_by_name(db_session, "nonexistent")
        assert result is None

    def test_get_task_by_name_case_sensitive(self, db_session: Session) -> None:
        """Test that name lookup is case-sensitive."""
        create_task(db_session, name="backup", command="ls")
        db_session.commit()

        result = get_task_by_name(db_session, "BACKUP")
        assert result is None


class TestListTasks:
    """Tests for list_tasks function."""

    def test_list_tasks_empty(self, db_session: Session) -> None:
        """Test listing tasks when none exist."""
        tasks = list_tasks(db_session)
        assert tasks == []

    def test_list_tasks_all(self, db_session: Session) -> None:
        """Test listing all tasks."""
        create_task(db_session, name="task1", command="echo 1")
        create_task(db_session, name="task2", command="echo 2")
        create_task(db_session, name="task3", command="echo 3")
        db_session.commit()

        tasks = list_tasks(db_session)
        assert len(tasks) == 3
        names = {t.name for t in tasks}
        assert names == {"task1", "task2", "task3"}

    def test_list_tasks_with_filter(self, db_session: Session) -> None:
        """Test listing tasks with name filter."""
        create_task(db_session, name="backup-daily", command="echo 1")
        create_task(db_session, name="backup-weekly", command="echo 2")
        create_task(db_session, name="cleanup", command="echo 3")
        db_session.commit()

        tasks = list_tasks(db_session, name_contains="backup")
        assert len(tasks) == 2
        names = {t.name for t in tasks}
        assert names == {"backup-daily", "backup-weekly"}

    def test_list_tasks_filter_case_insensitive(self, db_session: Session) -> None:
        """Test that name filter is case-insensitive."""
        create_task(db_session, name="BACKUP-Daily", command="echo 1")
        create_task(db_session, name="backup-weekly", command="echo 2")
        db_session.commit()

        tasks = list_tasks(db_session, name_contains="backup")
        assert len(tasks) == 2

        tasks = list_tasks(db_session, name_contains="BACKUP")
        assert len(tasks) == 2

    def test_list_tasks_filter_no_matches(self, db_session: Session) -> None:
        """Test filter with no matches returns empty list."""
        create_task(db_session, name="task1", command="echo 1")
        db_session.commit()

        tasks = list_tasks(db_session, name_contains="nonexistent")
        assert tasks == []


class TestUpdateTask:
    """Tests for update_task function."""

    def test_update_task_single_field(self, db_session: Session) -> None:
        """Test updating a single field."""
        task = create_task(db_session, name="test", command="echo old")
        db_session.commit()

        updated = update_task(db_session, task.id, command="echo new")

        assert updated.id == task.id
        assert updated.command == "echo new"
        assert updated.name == "test"  # Unchanged

    def test_update_task_multiple_fields(self, db_session: Session) -> None:
        """Test updating multiple fields."""
        task = create_task(db_session, name="test", command="echo old")
        db_session.commit()

        updated = update_task(
            db_session,
            task.id,
            name="updated",
            command="echo new",
            description="Updated description",
        )

        assert updated.name == "updated"
        assert updated.command == "echo new"
        assert updated.description == "Updated description"

    def test_update_task_not_found(self, db_session: Session) -> None:
        """Test updating non-existent task raises error."""
        fake_id = "00000000-0000-0000-0000-000000000000"

        with pytest.raises(TaskNotFoundError) as exc_info:
            update_task(db_session, fake_id, command="echo new")

        assert exc_info.value.task_id == fake_id

    def test_update_task_duplicate_name(self, db_session: Session) -> None:
        """Test updating name to duplicate raises error."""
        create_task(db_session, name="task1", command="echo 1")
        task2 = create_task(db_session, name="task2", command="echo 2")
        db_session.commit()

        with pytest.raises(DuplicateTaskError) as exc_info:
            update_task(db_session, task2.id, name="task1")

        assert exc_info.value.name == "task1"

    def test_update_task_same_name_allowed(self, db_session: Session) -> None:
        """Test updating task with its own name is allowed."""
        task = create_task(db_session, name="test", command="echo old")
        db_session.commit()

        # Should not raise error when "updating" to the same name
        updated = update_task(db_session, task.id, name="test", command="echo new")
        assert updated.name == "test"
        assert updated.command == "echo new"


class TestDeleteTask:
    """Tests for delete_task function."""

    def test_delete_task_exists(self, db_session: Session) -> None:
        """Test deleting an existing task."""
        task = create_task(db_session, name="test", command="echo test")
        db_session.commit()
        task_id = task.id

        deleted = delete_task(db_session, task_id)

        # Should return the deleted task
        assert deleted.id == task_id
        assert deleted.name == "test"

        # Task should no longer exist
        db_session.commit()
        result = get_task_by_name(db_session, "test")
        assert result is None

    def test_delete_task_not_found(self, db_session: Session) -> None:
        """Test deleting non-existent task raises error."""
        fake_id = "00000000-0000-0000-0000-000000000000"

        with pytest.raises(TaskNotFoundError) as exc_info:
            delete_task(db_session, fake_id)

        assert exc_info.value.task_id == fake_id

    def test_delete_task_multiple(self, db_session: Session) -> None:
        """Test deleting multiple tasks."""
        task1 = create_task(db_session, name="task1", command="echo 1")
        task2 = create_task(db_session, name="task2", command="echo 2")
        db_session.commit()

        delete_task(db_session, task1.id)
        delete_task(db_session, task2.id)
        db_session.commit()

        tasks = list_tasks(db_session)
        assert tasks == []
