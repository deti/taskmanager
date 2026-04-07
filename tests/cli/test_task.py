"""Tests for task CLI commands."""


import pytest
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from taskmanager.cli import app
from taskmanager.database import Base
from taskmanager.services.task_service import create_task


runner = CliRunner()


@pytest.fixture
def setup_db(db_engine):
    """Set up database tables before each test."""
    Base.metadata.create_all(db_engine)
    yield
    Base.metadata.drop_all(db_engine)


@pytest.fixture
def mock_db(db_session: Session, monkeypatch):
    """Mock get_db to return the test session."""
    from contextlib import contextmanager

    @contextmanager
    def _get_test_db():
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    monkeypatch.setattr("taskmanager.cli.task.get_db", _get_test_db)
    return db_session


class TestTaskAdd:
    """Tests for the 'task add' command."""

    def test_add_task_success(self, setup_db, mock_db):
        """Test adding a new task successfully."""
        result = runner.invoke(
            app,
            [
                "task",
                "add",
                "--name",
                "backup",
                "--command",
                "rsync -av /data /backup",
                "--description",
                "Daily backup job",
                "--shell",
                "/bin/bash",
            ],
        )

        assert result.exit_code == 0
        assert "Task 'backup' created" in result.stdout
        assert "✓" in result.stdout

    def test_add_task_minimal(self, setup_db, mock_db):
        """Test adding a task with minimal required fields."""
        result = runner.invoke(
            app,
            [
                "task",
                "add",
                "--name",
                "hello",
                "--command",
                "echo hello",
            ],
        )

        assert result.exit_code == 0
        assert "Task 'hello' created" in result.stdout

    def test_add_duplicate_task_name(self, setup_db, mock_db):
        """Test that adding a duplicate task name fails."""
        # Create initial task
        create_task(mock_db, name="backup", command="rsync -av /data /backup")

        # Try to create duplicate
        result = runner.invoke(
            app,
            [
                "task",
                "add",
                "--name",
                "backup",
                "--command",
                "different command",
            ],
        )

        assert result.exit_code == 1
        # Error messages go to stderr
        output = result.stdout + result.stderr
        assert "Error:" in output
        assert "already exists" in output


class TestTaskList:
    """Tests for the 'task list' command."""

    def test_list_empty(self, setup_db, mock_db):
        """Test listing when no tasks exist."""
        result = runner.invoke(app, ["task", "list"])

        assert result.exit_code == 0
        assert "No tasks found" in result.stdout

    def test_list_multiple_tasks(self, setup_db, mock_db):
        """Test listing multiple tasks."""
        create_task(mock_db, name="task1", command="echo one")
        create_task(mock_db, name="task2", command="echo two")
        create_task(
            mock_db,
            name="task3",
            command="echo three",
            description="Third task",
        )

        result = runner.invoke(app, ["task", "list"])

        assert result.exit_code == 0
        assert "task1" in result.stdout
        assert "task2" in result.stdout
        assert "task3" in result.stdout
        assert "echo one" in result.stdout

    def test_list_truncates_long_commands(self, setup_db, mock_db):
        """Test that long commands are truncated in the list view."""
        long_command = "echo " + "x" * 100
        create_task(mock_db, name="longcmd", command=long_command)

        result = runner.invoke(app, ["task", "list"])

        assert result.exit_code == 0
        assert "longcmd" in result.stdout
        # Rich uses ellipsis character "…" for truncation
        assert ("..." in result.stdout or "…" in result.stdout)


class TestTaskShow:
    """Tests for the 'task show' command."""

    def test_show_existing_task(self, setup_db, mock_db):
        """Test showing details of an existing task."""
        create_task(
            mock_db,
            name="backup",
            command="rsync -av /data /backup",
            description="Daily backup",
            shell="/bin/bash",
        )

        result = runner.invoke(app, ["task", "show", "backup"])

        assert result.exit_code == 0
        assert "backup" in result.stdout
        assert "rsync -av /data /backup" in result.stdout
        assert "Daily backup" in result.stdout
        assert "/bin/bash" in result.stdout
        assert "ID:" in result.stdout
        assert "Created:" in result.stdout

    def test_show_task_without_description(self, setup_db, mock_db):
        """Test showing a task that has no description."""
        create_task(mock_db, name="simple", command="echo hello")

        result = runner.invoke(app, ["task", "show", "simple"])

        assert result.exit_code == 0
        assert "simple" in result.stdout
        assert "echo hello" in result.stdout

    def test_show_nonexistent_task(self, setup_db, mock_db):
        """Test showing a task that doesn't exist."""
        result = runner.invoke(app, ["task", "show", "nonexistent"])

        assert result.exit_code == 1
        # Error messages go to stderr
        output = result.stdout + result.stderr
        assert "Error:" in output
        assert "not found" in output


class TestTaskEdit:
    """Tests for the 'task edit' command."""

    def test_edit_task_name(self, setup_db, mock_db):
        """Test editing a task's name."""
        create_task(mock_db, name="oldname", command="echo hello")

        result = runner.invoke(
            app,
            ["task", "edit", "oldname", "--name", "newname"],
        )

        assert result.exit_code == 0
        assert "updated" in result.stdout

    def test_edit_task_command(self, setup_db, mock_db):
        """Test editing a task's command."""
        create_task(mock_db, name="task1", command="echo old")

        result = runner.invoke(
            app,
            ["task", "edit", "task1", "--command", "echo new"],
        )

        assert result.exit_code == 0
        assert "updated" in result.stdout

    def test_edit_multiple_fields(self, setup_db, mock_db):
        """Test editing multiple fields at once."""
        create_task(mock_db, name="task1", command="echo old")

        result = runner.invoke(
            app,
            [
                "task",
                "edit",
                "task1",
                "--command",
                "echo new",
                "--description",
                "Updated task",
                "--shell",
                "/bin/zsh",
            ],
        )

        assert result.exit_code == 0
        assert "updated" in result.stdout

    def test_edit_no_updates_provided(self, setup_db, mock_db):
        """Test editing with no update flags provided."""
        create_task(mock_db, name="task1", command="echo hello")

        result = runner.invoke(app, ["task", "edit", "task1"])

        assert result.exit_code == 0
        assert "No updates provided" in result.stdout

    def test_edit_nonexistent_task(self, setup_db, mock_db):
        """Test editing a task that doesn't exist."""
        result = runner.invoke(
            app,
            ["task", "edit", "nonexistent", "--command", "echo new"],
        )

        assert result.exit_code == 1
        # Error messages go to stderr
        output = result.stdout + result.stderr
        assert "Error:" in output
        assert "not found" in output

    def test_edit_to_duplicate_name(self, setup_db, mock_db):
        """Test editing a task to a name that already exists."""
        create_task(mock_db, name="task1", command="echo one")
        create_task(mock_db, name="task2", command="echo two")

        result = runner.invoke(
            app,
            ["task", "edit", "task1", "--name", "task2"],
        )

        assert result.exit_code == 1
        # Error messages go to stderr
        output = result.stdout + result.stderr
        assert "Error:" in output
        assert "already exists" in output


class TestTaskRemove:
    """Tests for the 'task remove' command."""

    def test_remove_task_with_yes_flag(self, setup_db, mock_db):
        """Test removing a task with --yes flag (no prompt)."""
        create_task(mock_db, name="task1", command="echo hello")

        result = runner.invoke(app, ["task", "remove", "task1", "--yes"])

        assert result.exit_code == 0
        assert "removed" in result.stdout
        assert "✓" in result.stdout

    def test_remove_task_confirm_yes(self, setup_db, mock_db):
        """Test removing a task with confirmation prompt (user says yes)."""
        create_task(mock_db, name="task1", command="echo hello")

        result = runner.invoke(app, ["task", "remove", "task1"], input="y\n")

        assert result.exit_code == 0
        assert "removed" in result.stdout

    def test_remove_task_confirm_no(self, setup_db, mock_db):
        """Test removing a task with confirmation prompt (user says no)."""
        create_task(mock_db, name="task1", command="echo hello")

        result = runner.invoke(app, ["task", "remove", "task1"], input="n\n")

        assert result.exit_code == 0
        assert "Cancelled" in result.stdout

    def test_remove_nonexistent_task(self, setup_db, mock_db):
        """Test removing a task that doesn't exist."""
        result = runner.invoke(app, ["task", "remove", "nonexistent", "--yes"])

        assert result.exit_code == 1
        # Error messages go to stderr
        output = result.stdout + result.stderr
        assert "Error:" in output
        assert "not found" in output


class TestTaskIntegration:
    """Integration tests combining multiple operations."""

    def test_full_workflow(self, setup_db, mock_db):
        """Test a complete workflow: add, list, show, edit, remove."""
        # Add task
        result = runner.invoke(
            app,
            [
                "task",
                "add",
                "--name",
                "workflow",
                "--command",
                "echo start",
                "--description",
                "Test workflow",
            ],
        )
        assert result.exit_code == 0

        # List tasks
        result = runner.invoke(app, ["task", "list"])
        assert result.exit_code == 0
        assert "workflow" in result.stdout

        # Show task
        result = runner.invoke(app, ["task", "show", "workflow"])
        assert result.exit_code == 0
        assert "Test workflow" in result.stdout

        # Edit task
        result = runner.invoke(
            app,
            ["task", "edit", "workflow", "--command", "echo updated"],
        )
        assert result.exit_code == 0

        # Verify edit
        result = runner.invoke(app, ["task", "show", "workflow"])
        assert result.exit_code == 0
        assert "echo updated" in result.stdout

        # Remove task
        result = runner.invoke(app, ["task", "remove", "workflow", "--yes"])
        assert result.exit_code == 0

        # Verify removal
        result = runner.invoke(app, ["task", "list"])
        assert result.exit_code == 0
        assert "No tasks found" in result.stdout
