"""Tests for data export/import CLI commands."""

from pathlib import Path

import pytest
import yaml
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from taskmanager.cli import app
from taskmanager.database import Base
from taskmanager.models import ActionType, Hook, Schedule, Task, TriggerType
from taskmanager.services.hook_service import create_hook
from taskmanager.services.schedule_service import create_schedule
from taskmanager.services.task_service import create_task, get_task_by_name


runner = CliRunner()


@pytest.fixture
def setup_db(db_engine):
    """Set up database tables before each test."""
    Base.metadata.create_all(db_engine)
    yield
    Base.metadata.drop_all(db_engine)


@pytest.fixture
def mock_db(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Session:
    """Mock get_db to return the test session."""
    from collections.abc import Iterator
    from contextlib import contextmanager

    @contextmanager
    def _get_test_db() -> Iterator[Session]:
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    monkeypatch.setattr("taskmanager.cli.data.get_db", _get_test_db)
    return db_session


@pytest.fixture
def sample_data(mock_db: Session):
    """Create sample tasks, schedules, and hooks for testing."""
    # Create tasks
    task1 = create_task(
        mock_db,
        name="backup",
        command="tar -czf backup.tar.gz /data",
        description="Daily backup",
    )
    task2 = create_task(
        mock_db,
        name="cleanup",
        command="rm -rf /tmp/*",
    )
    mock_db.flush()

    # Create schedules
    create_schedule(
        mock_db,
        task_id=task1.id,
        trigger_type=TriggerType.CRON,
        trigger_config={"cron": "0 2 * * *"},
    )
    create_schedule(
        mock_db,
        task_id=task2.id,
        trigger_type=TriggerType.INTERVAL,
        trigger_config={"interval": {"hours": 6}},
    )
    mock_db.flush()

    # Create hooks
    create_hook(
        mock_db,
        name="notify",
        event_type="task.success",
        action_type=ActionType.SHELL,
        action_config='{"command": "echo done"}',
        task_filter=task1.id,
    )
    create_hook(
        mock_db,
        name="log-failure",
        event_type="task.failed",
        action_type=ActionType.LOG,
        action_config='{"message": "Task failed"}',
        task_filter=None,
    )
    mock_db.commit()


class TestExportCommand:
    """Tests for the 'data export' command."""

    def test_export_creates_file(
        self, setup_db, mock_db: Session, tmp_path: Path
    ) -> None:
        """Test that export command creates a YAML file."""
        output_file = tmp_path / "export.yaml"

        result = runner.invoke(app, ["data", "export", "--output", str(output_file)])

        assert result.exit_code == 0
        assert output_file.exists()
        assert "Exported 0 tasks, 0 schedules, 0 hooks" in result.stdout

    def test_export_with_data(
        self, setup_db, sample_data, tmp_path: Path
    ) -> None:
        """Test exporting data creates valid YAML with correct counts."""
        output_file = tmp_path / "export.yaml"

        result = runner.invoke(app, ["data", "export", "-o", str(output_file)])

        assert result.exit_code == 0
        assert output_file.exists()
        assert "Exported 2 tasks, 2 schedules, 2 hooks" in result.stdout

        # Verify YAML structure
        with output_file.open() as f:
            data = yaml.safe_load(f)

        assert data["version"] == "1.0"
        assert "exported_at" in data
        assert len(data["tasks"]) == 2
        assert len(data["schedules"]) == 2
        assert len(data["hooks"]) == 2

    def test_export_yaml_structure(
        self, setup_db, sample_data, tmp_path: Path
    ) -> None:
        """Test that exported YAML has correct structure and content."""
        output_file = tmp_path / "export.yaml"

        runner.invoke(app, ["data", "export", "-o", str(output_file)])

        with output_file.open() as f:
            data = yaml.safe_load(f)

        # Check task structure
        backup_task = next(t for t in data["tasks"] if t["name"] == "backup")
        assert backup_task["command"] == "tar -czf backup.tar.gz /data"
        assert backup_task["description"] == "Daily backup"
        assert "metadata" in backup_task

        # Check schedule structure (uses task names, not IDs)
        backup_schedule = next(
            s for s in data["schedules"] if s["task_name"] == "backup"
        )
        assert backup_schedule["trigger_type"] == "cron"
        assert backup_schedule["enabled"] is True

        # Check hook structure
        notify_hook = next(h for h in data["hooks"] if h["name"] == "notify")
        assert notify_hook["task_filter_name"] == "backup"
        assert notify_hook["action_type"] == "shell"

        global_hook = next(h for h in data["hooks"] if h["name"] == "log-failure")
        assert global_hook["task_filter_name"] is None

    def test_export_permission_denied(self, setup_db, mock_db: Session) -> None:
        """Test export with permission denied error."""
        result = runner.invoke(app, ["data", "export", "-o", "/root/forbidden.yaml"])

        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "Permission denied" in output or "Error" in output


class TestImportCommand:
    """Tests for the 'data import' command."""

    def test_import_from_file(
        self, setup_db, mock_db: Session, tmp_path: Path
    ) -> None:
        """Test importing data from YAML file."""
        # Create export file
        import_file = tmp_path / "import.yaml"
        data = {
            "version": "1.0",
            "exported_at": "2026-04-08T12:00:00Z",
            "tasks": [
                {
                    "name": "backup",
                    "command": "tar -czf backup.tar.gz",
                    "description": None,
                    "shell": "/bin/sh",
                    "metadata": None,
                }
            ],
            "schedules": [],
            "hooks": [],
        }
        with import_file.open("w") as f:
            yaml.safe_dump(data, f)

        result = runner.invoke(app, ["data", "import", "--input", str(import_file)])

        assert result.exit_code == 0
        assert "Import Summary" in result.stdout
        assert "1 created, 0 updated, 0 skipped" in result.stdout

        # Verify task was created
        task = get_task_by_name(mock_db, "backup")
        assert task is not None
        assert task.command == "tar -czf backup.tar.gz"

    def test_import_with_schedules_and_hooks(
        self, setup_db, mock_db: Session, tmp_path: Path
    ) -> None:
        """Test importing tasks with schedules and hooks."""
        import_file = tmp_path / "full-import.yaml"
        data = {
            "version": "1.0",
            "exported_at": "2026-04-08T12:00:00Z",
            "tasks": [
                {
                    "name": "backup",
                    "command": "tar -czf backup.tar.gz",
                    "description": None,
                    "shell": "/bin/sh",
                    "metadata": None,
                }
            ],
            "schedules": [
                {
                    "task_name": "backup",
                    "trigger_type": "cron",
                    "trigger_config": '{"cron": "0 2 * * *"}',
                    "enabled": True,
                }
            ],
            "hooks": [
                {
                    "name": "notify",
                    "event_type": "task.success",
                    "task_filter_name": "backup",
                    "action_type": "shell",
                    "action_config": '{"command": "echo done"}',
                    "enabled": True,
                }
            ],
        }
        with import_file.open("w") as f:
            yaml.safe_dump(data, f)

        result = runner.invoke(app, ["data", "import", "-i", str(import_file)])

        assert result.exit_code == 0
        assert "Import Summary" in result.stdout

        # Verify all entities were created
        task = get_task_by_name(mock_db, "backup")
        assert task is not None

        schedules = mock_db.query(Schedule).filter_by(task_id=task.id).all()
        assert len(schedules) == 1

        hooks = mock_db.query(Hook).filter_by(name="notify").all()
        assert len(hooks) == 1

    def test_import_conflict_error_default(
        self, setup_db, sample_data, tmp_path: Path
    ) -> None:
        """Test import with conflict (default error strategy)."""
        import_file = tmp_path / "import.yaml"
        data = {
            "version": "1.0",
            "exported_at": "2026-04-08T12:00:00Z",
            "tasks": [
                {
                    "name": "backup",  # Already exists
                    "command": "new command",
                    "description": None,
                    "shell": "/bin/sh",
                    "metadata": None,
                }
            ],
            "schedules": [],
            "hooks": [],
        }
        with import_file.open("w") as f:
            yaml.safe_dump(data, f)

        result = runner.invoke(app, ["data", "import", "-i", str(import_file)])

        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "Error" in output

    def test_import_conflict_skip(
        self, setup_db, sample_data, tmp_path: Path
    ) -> None:
        """Test import with --on-conflict skip."""
        import_file = tmp_path / "import.yaml"
        data = {
            "version": "1.0",
            "exported_at": "2026-04-08T12:00:00Z",
            "tasks": [
                {
                    "name": "backup",  # Already exists
                    "command": "new command",
                    "description": None,
                    "shell": "/bin/sh",
                    "metadata": None,
                },
                {
                    "name": "new-task",
                    "command": "echo new",
                    "description": None,
                    "shell": "/bin/sh",
                    "metadata": None,
                },
            ],
            "schedules": [],
            "hooks": [],
        }
        with import_file.open("w") as f:
            yaml.safe_dump(data, f)

        result = runner.invoke(
            app, ["data", "import", "-i", str(import_file), "--on-conflict", "skip"]
        )

        assert result.exit_code == 0
        assert "Import Summary" in result.stdout
        # 1 skipped (backup), 1 created (new-task)
        assert "1 created, 0 updated, 1 skipped" in result.stdout

    def test_import_conflict_overwrite(
        self, setup_db, sample_data, mock_db: Session, tmp_path: Path
    ) -> None:
        """Test import with --on-conflict overwrite."""
        import_file = tmp_path / "import.yaml"
        data = {
            "version": "1.0",
            "exported_at": "2026-04-08T12:00:00Z",
            "tasks": [
                {
                    "name": "backup",
                    "command": "NEW COMMAND",
                    "description": "Updated description",
                    "shell": "/bin/bash",
                    "metadata": None,
                }
            ],
            "schedules": [],
            "hooks": [],
        }
        with import_file.open("w") as f:
            yaml.safe_dump(data, f)

        result = runner.invoke(
            app,
            ["data", "import", "-i", str(import_file), "--on-conflict", "overwrite"],
        )

        assert result.exit_code == 0
        assert "0 created, 1 updated, 0 skipped" in result.stdout

        # Verify task was updated
        task = get_task_by_name(mock_db, "backup")
        assert task is not None
        assert task.command == "NEW COMMAND"
        assert task.description == "Updated description"
        assert task.shell == "/bin/bash"

    def test_import_file_not_found(self, setup_db, mock_db: Session) -> None:
        """Test import with non-existent file."""
        result = runner.invoke(
            app, ["data", "import", "-i", "/nonexistent/file.yaml"]
        )

        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "File not found" in output

    def test_import_invalid_yaml(
        self, setup_db, mock_db: Session, tmp_path: Path
    ) -> None:
        """Test import with invalid YAML syntax."""
        import_file = tmp_path / "invalid.yaml"
        import_file.write_text("invalid: yaml: syntax: [unclosed")

        result = runner.invoke(app, ["data", "import", "-i", str(import_file)])

        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "Invalid YAML format" in output or "Error" in output

    def test_import_empty_yaml(
        self, setup_db, mock_db: Session, tmp_path: Path
    ) -> None:
        """Test import with empty YAML file."""
        import_file = tmp_path / "empty.yaml"
        import_file.write_text("")

        result = runner.invoke(app, ["data", "import", "-i", str(import_file)])

        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "empty" in output.lower() or "Error" in output

    def test_import_invalid_conflict_strategy(
        self, setup_db, mock_db: Session, tmp_path: Path
    ) -> None:
        """Test import with invalid --on-conflict value."""
        import_file = tmp_path / "import.yaml"
        data = {
            "version": "1.0",
            "tasks": [],
            "schedules": [],
            "hooks": [],
        }
        with import_file.open("w") as f:
            yaml.safe_dump(data, f)

        result = runner.invoke(
            app,
            ["data", "import", "-i", str(import_file), "--on-conflict", "invalid"],
        )

        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "Invalid --on-conflict value" in output

    def test_round_trip_export_import(
        self, setup_db, sample_data, mock_db: Session, tmp_path: Path
    ) -> None:
        """Test round-trip: export → delete all → import → verify."""
        export_file = tmp_path / "export.yaml"

        # Export
        result = runner.invoke(app, ["data", "export", "-o", str(export_file)])
        assert result.exit_code == 0

        # Delete all entities
        mock_db.query(Hook).delete()
        mock_db.query(Schedule).delete()
        mock_db.query(Task).delete()
        mock_db.commit()

        # Verify empty
        assert mock_db.query(Task).count() == 0
        assert mock_db.query(Schedule).count() == 0
        assert mock_db.query(Hook).count() == 0

        # Import
        result = runner.invoke(app, ["data", "import", "-i", str(export_file)])
        assert result.exit_code == 0

        # Verify all entities restored
        assert mock_db.query(Task).count() == 2
        assert mock_db.query(Schedule).count() == 2
        assert mock_db.query(Hook).count() == 2

        # Verify specific task
        backup = get_task_by_name(mock_db, "backup")
        assert backup is not None
        assert backup.command == "tar -czf backup.tar.gz /data"
        assert backup.description == "Daily backup"
