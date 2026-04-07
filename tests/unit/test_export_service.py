"""Unit tests for export service layer.

Tests export and import operations with various conflict resolution strategies
using in-memory SQLite database.
"""

import json
from datetime import datetime

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from taskmanager.database import Base
from taskmanager.exceptions import (
    DuplicateTaskError,
    TaskNotFoundError,
)
from taskmanager.models import ActionType, Hook, Schedule, Task, TriggerType
from taskmanager.services.export_service import export_all, import_all
from taskmanager.services.hook_service import create_hook
from taskmanager.services.schedule_service import create_schedule
from taskmanager.services.task_service import create_task, get_task_by_name


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


class TestExportAll:
    """Tests for export_all function."""

    def test_export_empty_database(self, db_session: Session) -> None:
        """Test exporting from empty database returns empty lists."""
        result = export_all(db_session)

        assert result["version"] == "1.0"
        assert "exported_at" in result
        assert result["tasks"] == []
        assert result["schedules"] == []
        assert result["hooks"] == []

    def test_export_tasks_only(self, db_session: Session) -> None:
        """Test exporting tasks without schedules or hooks."""
        # Create test tasks
        create_task(
            db_session,
            name="backup",
            command="tar -czf backup.tar.gz /data",
            description="Daily backup",
            shell="/bin/bash",
        )
        create_task(
            db_session,
            name="cleanup",
            command="rm -rf /tmp/*",
            description=None,
            shell="/bin/sh",
        )
        db_session.commit()

        result = export_all(db_session)

        assert len(result["tasks"]) == 2
        assert result["schedules"] == []
        assert result["hooks"] == []

        # Verify task data structure
        backup_task = next(t for t in result["tasks"] if t["name"] == "backup")
        assert backup_task["command"] == "tar -czf backup.tar.gz /data"
        assert backup_task["description"] == "Daily backup"
        assert backup_task["shell"] == "/bin/bash"
        assert backup_task["metadata"] is None

    def test_export_full_database(self, db_session: Session) -> None:
        """Test exporting tasks, schedules, and hooks together."""
        # Create tasks
        task1 = create_task(
            db_session,
            name="backup",
            command="tar -czf backup.tar.gz /data",
        )
        task2 = create_task(
            db_session,
            name="cleanup",
            command="rm -rf /tmp/*",
        )
        db_session.flush()

        # Create schedules
        create_schedule(
            db_session,
            task_id=task1.id,
            trigger_type=TriggerType.CRON,
            trigger_config={"cron": "0 2 * * *"},
            enabled=True,
        )
        create_schedule(
            db_session,
            task_id=task2.id,
            trigger_type=TriggerType.INTERVAL,
            trigger_config={"interval": {"hours": 6}},
            enabled=False,
        )
        db_session.flush()

        # Create hooks
        create_hook(
            db_session,
            name="notify-success",
            event_type="task.success",
            action_type=ActionType.SHELL,
            action_config='{"command": "echo done"}',
            task_filter=task1.id,
            enabled=True,
        )
        create_hook(
            db_session,
            name="global-failure",
            event_type="task.failed",
            action_type=ActionType.LOG,
            action_config='{"message": "Task failed", "level": "ERROR"}',
            task_filter=None,
            enabled=True,
        )
        db_session.commit()

        result = export_all(db_session)

        # Verify counts
        assert len(result["tasks"]) == 2
        assert len(result["schedules"]) == 2
        assert len(result["hooks"]) == 2

        # Verify schedule references task names (not IDs)
        backup_schedule = next(
            s for s in result["schedules"] if s["task_name"] == "backup"
        )
        assert backup_schedule["trigger_type"] == "cron"
        assert backup_schedule["trigger_config"] == '{"cron": "0 2 * * *"}'
        assert backup_schedule["enabled"] is True

        cleanup_schedule = next(
            s for s in result["schedules"] if s["task_name"] == "cleanup"
        )
        assert cleanup_schedule["trigger_type"] == "interval"
        assert cleanup_schedule["enabled"] is False

        # Verify hook references task names (or null for global)
        notify_hook = next(h for h in result["hooks"] if h["name"] == "notify-success")
        assert notify_hook["task_filter_name"] == "backup"
        assert notify_hook["action_type"] == "shell"

        global_hook = next(h for h in result["hooks"] if h["name"] == "global-failure")
        assert global_hook["task_filter_name"] is None
        assert global_hook["action_type"] == "log"

    def test_export_produces_valid_yaml(self, db_session: Session) -> None:
        """Test that exported data can be serialized to valid YAML."""
        # Create sample data
        create_task(db_session, name="test", command="echo test")
        db_session.commit()

        result = export_all(db_session)

        # Serialize to YAML and parse back
        yaml_str = yaml.safe_dump(result, default_flow_style=False)
        parsed = yaml.safe_load(yaml_str)

        assert parsed["version"] == "1.0"
        assert len(parsed["tasks"]) == 1
        assert parsed["tasks"][0]["name"] == "test"


class TestImportAll:
    """Tests for import_all function."""

    def test_import_empty_data(self, db_session: Session) -> None:
        """Test importing empty data succeeds."""
        data = {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "tasks": [],
            "schedules": [],
            "hooks": [],
        }

        stats = import_all(db_session, data)

        assert stats["tasks_created"] == 0
        assert stats["schedules_created"] == 0
        assert stats["hooks_created"] == 0

    def test_import_invalid_data_structure(self, db_session: Session) -> None:
        """Test importing invalid data raises ValueError."""
        # Missing required keys
        data = {"tasks": []}

        with pytest.raises(ValueError, match="missing required key"):
            import_all(db_session, data)

    def test_import_tasks_fresh_database(self, db_session: Session) -> None:
        """Test importing tasks into fresh database."""
        data = {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "tasks": [
                {
                    "name": "backup",
                    "command": "tar -czf backup.tar.gz /data",
                    "description": "Daily backup",
                    "shell": "/bin/bash",
                    "metadata": None,
                },
                {
                    "name": "cleanup",
                    "command": "rm -rf /tmp/*",
                    "description": None,
                    "shell": "/bin/sh",
                    "metadata": None,
                },
            ],
            "schedules": [],
            "hooks": [],
        }

        stats = import_all(db_session, data)

        assert stats["tasks_created"] == 2
        assert stats["tasks_updated"] == 0
        assert stats["tasks_skipped"] == 0

        # Verify tasks were created
        backup = get_task_by_name(db_session, "backup")
        assert backup is not None
        assert backup.command == "tar -czf backup.tar.gz /data"
        assert backup.description == "Daily backup"
        assert backup.shell == "/bin/bash"

    def test_import_conflict_error_strategy(self, db_session: Session) -> None:
        """Test import with on_conflict='error' raises error on duplicate."""
        # Create existing task
        create_task(db_session, name="backup", command="old command")
        db_session.commit()

        data = {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "tasks": [
                {
                    "name": "backup",
                    "command": "new command",
                    "description": None,
                    "shell": "/bin/sh",
                    "metadata": None,
                }
            ],
            "schedules": [],
            "hooks": [],
        }

        with pytest.raises(DuplicateTaskError):
            import_all(db_session, data, on_conflict="error")

    def test_import_conflict_skip_strategy(self, db_session: Session) -> None:
        """Test import with on_conflict='skip' skips existing tasks."""
        # Create existing task
        create_task(db_session, name="backup", command="old command")
        db_session.commit()

        data = {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "tasks": [
                {
                    "name": "backup",
                    "command": "new command",
                    "description": None,
                    "shell": "/bin/sh",
                    "metadata": None,
                },
                {
                    "name": "cleanup",
                    "command": "rm -rf /tmp/*",
                    "description": None,
                    "shell": "/bin/sh",
                    "metadata": None,
                },
            ],
            "schedules": [],
            "hooks": [],
        }

        stats = import_all(db_session, data, on_conflict="skip")

        assert stats["tasks_created"] == 1  # Only cleanup
        assert stats["tasks_updated"] == 0
        assert stats["tasks_skipped"] == 1  # backup skipped

        # Verify existing task unchanged
        backup = get_task_by_name(db_session, "backup")
        assert backup.command == "old command"

    def test_import_conflict_overwrite_strategy(self, db_session: Session) -> None:
        """Test import with on_conflict='overwrite' updates existing tasks."""
        # Create existing task
        create_task(
            db_session, name="backup", command="old command", description="old desc"
        )
        db_session.commit()

        data = {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "tasks": [
                {
                    "name": "backup",
                    "command": "new command",
                    "description": "new desc",
                    "shell": "/bin/bash",
                    "metadata": None,
                }
            ],
            "schedules": [],
            "hooks": [],
        }

        stats = import_all(db_session, data, on_conflict="overwrite")

        assert stats["tasks_created"] == 0
        assert stats["tasks_updated"] == 1
        assert stats["tasks_skipped"] == 0

        # Verify task was updated
        backup = get_task_by_name(db_session, "backup")
        assert backup.command == "new command"
        assert backup.description == "new desc"
        assert backup.shell == "/bin/bash"

    def test_import_schedules_with_task_resolution(self, db_session: Session) -> None:
        """Test importing schedules resolves task names to IDs."""
        data = {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "tasks": [
                {
                    "name": "backup",
                    "command": "tar -czf backup.tar.gz /data",
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
            "hooks": [],
        }

        stats = import_all(db_session, data)

        assert stats["tasks_created"] == 1
        assert stats["schedules_created"] == 1

        # Verify schedule references correct task
        task = get_task_by_name(db_session, "backup")
        schedules = db_session.query(Schedule).filter_by(task_id=task.id).all()
        assert len(schedules) == 1
        assert schedules[0].trigger_type == TriggerType.CRON

    def test_import_schedule_missing_task_reference(self, db_session: Session) -> None:
        """Test importing schedule with non-existent task raises error."""
        data = {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "tasks": [],
            "schedules": [
                {
                    "task_name": "nonexistent",
                    "trigger_type": "cron",
                    "trigger_config": '{"cron": "0 2 * * *"}',
                    "enabled": True,
                }
            ],
            "hooks": [],
        }

        with pytest.raises(TaskNotFoundError, match="nonexistent"):
            import_all(db_session, data)

    def test_import_hooks_with_task_filter_resolution(self, db_session: Session) -> None:
        """Test importing hooks resolves task_filter names to IDs."""
        data = {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "tasks": [
                {
                    "name": "backup",
                    "command": "tar -czf backup.tar.gz /data",
                    "description": None,
                    "shell": "/bin/sh",
                    "metadata": None,
                }
            ],
            "schedules": [],
            "hooks": [
                {
                    "name": "notify-success",
                    "event_type": "task.success",
                    "task_filter_name": "backup",
                    "action_type": "shell",
                    "action_config": '{"command": "echo done"}',
                    "enabled": True,
                },
                {
                    "name": "global-failure",
                    "event_type": "task.failed",
                    "task_filter_name": None,
                    "action_type": "log",
                    "action_config": '{"message": "failed"}',
                    "enabled": True,
                },
            ],
        }

        stats = import_all(db_session, data)

        assert stats["tasks_created"] == 1
        assert stats["hooks_created"] == 2

        # Verify task-scoped hook
        task = get_task_by_name(db_session, "backup")
        scoped_hook = (
            db_session.query(Hook).filter_by(name="notify-success").one_or_none()
        )
        assert scoped_hook is not None
        assert scoped_hook.task_filter == task.id

        # Verify global hook
        global_hook = (
            db_session.query(Hook).filter_by(name="global-failure").one_or_none()
        )
        assert global_hook is not None
        assert global_hook.task_filter is None

    def test_import_hook_missing_task_reference(self, db_session: Session) -> None:
        """Test importing hook with non-existent task_filter raises error."""
        data = {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "tasks": [],
            "schedules": [],
            "hooks": [
                {
                    "name": "notify",
                    "event_type": "task.success",
                    "task_filter_name": "nonexistent",
                    "action_type": "shell",
                    "action_config": '{"command": "echo done"}',
                    "enabled": True,
                }
            ],
        }

        with pytest.raises(TaskNotFoundError, match="nonexistent"):
            import_all(db_session, data)

    def test_round_trip_export_import(self, db_session: Session) -> None:
        """Test round-trip: export → import → export produces identical data."""
        # Create original data
        task1 = create_task(db_session, name="backup", command="tar -czf backup.tar.gz")
        create_task(db_session, name="cleanup", command="rm -rf /tmp/*")
        db_session.flush()

        create_schedule(
            db_session,
            task_id=task1.id,
            trigger_type=TriggerType.CRON,
            trigger_config={"cron": "0 2 * * *"},
        )
        create_hook(
            db_session,
            name="notify",
            event_type="task.success",
            action_type=ActionType.SHELL,
            action_config='{"command": "echo done"}',
            task_filter=task1.id,
        )
        db_session.commit()

        # First export
        export1 = export_all(db_session)

        # Clear database
        db_session.query(Hook).delete()
        db_session.query(Schedule).delete()
        db_session.query(Task).delete()
        db_session.commit()

        # Import
        import_all(db_session, export1)
        db_session.commit()

        # Second export
        export2 = export_all(db_session)

        # Compare (excluding timestamps)
        assert len(export2["tasks"]) == len(export1["tasks"])
        assert len(export2["schedules"]) == len(export1["schedules"])
        assert len(export2["hooks"]) == len(export1["hooks"])

        # Compare task data
        for t1, t2 in zip(
            sorted(export1["tasks"], key=lambda x: x["name"]),
            sorted(export2["tasks"], key=lambda x: x["name"]),
            strict=True,
        ):
            assert t1["name"] == t2["name"]
            assert t1["command"] == t2["command"]
            assert t1["description"] == t2["description"]
            assert t1["shell"] == t2["shell"]

    def test_import_hook_conflict_resolution(self, db_session: Session) -> None:
        """Test hook conflict resolution strategies."""
        # Create existing task and hook
        task = create_task(db_session, name="backup", command="tar -czf")
        db_session.flush()
        create_hook(
            db_session,
            name="notify",
            event_type="task.success",
            action_type=ActionType.SHELL,
            action_config='{"command": "echo old"}',
            task_filter=task.id,
        )
        db_session.commit()

        # Data tries to import both the existing task and hook with changes
        data = {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "tasks": [
                {
                    "name": "backup",
                    "command": "tar -czf",
                    "description": None,
                    "shell": "/bin/sh",
                    "metadata": None,
                }
            ],
            "schedules": [],
            "hooks": [
                {
                    "name": "notify",
                    "event_type": "task.failed",
                    "task_filter_name": "backup",
                    "action_type": "shell",
                    "action_config": '{"command": "echo new"}',
                    "enabled": False,
                }
            ],
        }

        # Test error strategy - both task and hook conflict
        with pytest.raises(DuplicateTaskError):
            import_all(db_session, data, on_conflict="error")

        # Test skip strategy - task and hook both skipped
        stats = import_all(db_session, data, on_conflict="skip")
        assert stats["tasks_skipped"] == 1
        assert stats["hooks_skipped"] == 1
        assert stats["hooks_updated"] == 0

        # Test overwrite strategy - task and hook both updated
        stats = import_all(db_session, data, on_conflict="overwrite")
        assert stats["tasks_updated"] == 1
        assert stats["hooks_updated"] == 1
        assert stats["hooks_skipped"] == 0

        # Verify hook was updated
        hook = db_session.query(Hook).filter_by(name="notify").one()
        assert hook.event_type == "task.failed"
        assert hook.enabled is False
        config = json.loads(hook.action_config)
        assert config["command"] == "echo new"
