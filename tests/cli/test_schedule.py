"""Tests for schedule CLI commands."""

import pytest
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from taskmanager.cli import app
from taskmanager.database import Base
from taskmanager.models import Schedule, TriggerType
from taskmanager.services.schedule_service import create_schedule
from taskmanager.services.task_service import create_task


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

    monkeypatch.setattr("taskmanager.cli.schedule.get_db", _get_test_db)
    return db_session


@pytest.fixture
def sample_task(mock_db):
    """Create a sample task for testing."""
    return create_task(mock_db, name="test-task", command="echo hello")


class TestScheduleAdd:
    """Tests for the 'schedule add' command."""

    def test_add_schedule_cron(self, setup_db, mock_db, sample_task):
        """Test adding a schedule with CRON trigger."""
        result = runner.invoke(
            app,
            [
                "schedule",
                "add",
                "--task",
                "test-task",
                "--cron",
                "0 * * * *",
            ],
        )

        assert result.exit_code == 0
        assert "Schedule created" in result.stdout
        assert "✓" in result.stdout

        # Verify in database
        schedules = mock_db.query(Schedule).filter_by(task_id=sample_task.id).all()
        assert len(schedules) == 1
        assert schedules[0].trigger_type == TriggerType.CRON
        assert '"cron": "0 * * * *"' in schedules[0].trigger_config

    def test_add_schedule_interval_every(self, setup_db, mock_db, sample_task):
        """Test adding a schedule with INTERVAL trigger using --every."""
        result = runner.invoke(
            app,
            [
                "schedule",
                "add",
                "--task",
                "test-task",
                "--every",
                "30m",
            ],
        )

        assert result.exit_code == 0
        assert "Schedule created" in result.stdout

        # Verify in database
        schedules = mock_db.query(Schedule).filter_by(task_id=sample_task.id).all()
        assert len(schedules) == 1
        assert schedules[0].trigger_type == TriggerType.INTERVAL
        assert '"minutes": 30' in schedules[0].trigger_config

    def test_add_schedule_interval_variations(self, setup_db, mock_db):
        """Test different interval formats (s, m, h, d)."""
        # Create separate tasks for each schedule to avoid unique constraint
        create_task(mock_db, name="task1", command="echo 1")
        create_task(mock_db, name="task2", command="echo 2")
        create_task(mock_db, name="task3", command="echo 3")

        # Test seconds
        result = runner.invoke(app, ["schedule", "add", "--task", "task1", "--every", "5s"])
        assert result.exit_code == 0

        # Test hours
        result = runner.invoke(app, ["schedule", "add", "--task", "task2", "--every", "2h"])
        assert result.exit_code == 0

        # Test days
        result = runner.invoke(app, ["schedule", "add", "--task", "task3", "--every", "1d"])
        assert result.exit_code == 0

        # Verify in database
        schedules = mock_db.query(Schedule).all()
        assert len(schedules) == 3

    def test_add_schedule_once(self, setup_db, mock_db, sample_task):
        """Test adding a schedule with ONCE trigger."""
        result = runner.invoke(
            app,
            [
                "schedule",
                "add",
                "--task",
                "test-task",
                "--once",
                "2026-04-10T15:00:00",
            ],
        )

        assert result.exit_code == 0
        assert "Schedule created" in result.stdout

        # Verify in database
        schedules = mock_db.query(Schedule).filter_by(task_id=sample_task.id).all()
        assert len(schedules) == 1
        assert schedules[0].trigger_type == TriggerType.ONCE
        assert "2026-04-10T15:00:00" in schedules[0].trigger_config

    def test_add_schedule_enabled_flag(self, setup_db, mock_db, sample_task):
        """Test adding a schedule with --enabled flag (default)."""
        result = runner.invoke(
            app,
            [
                "schedule",
                "add",
                "--task",
                "test-task",
                "--cron",
                "0 * * * *",
                "--enabled",
            ],
        )

        assert result.exit_code == 0

        schedules = mock_db.query(Schedule).filter_by(task_id=sample_task.id).all()
        assert schedules[0].enabled is True

    def test_add_schedule_disabled_flag(self, setup_db, mock_db, sample_task):
        """Test adding a schedule with --disabled flag."""
        result = runner.invoke(
            app,
            [
                "schedule",
                "add",
                "--task",
                "test-task",
                "--cron",
                "0 * * * *",
                "--disabled",
            ],
        )

        assert result.exit_code == 0

        schedules = mock_db.query(Schedule).filter_by(task_id=sample_task.id).all()
        assert schedules[0].enabled is False

    def test_add_schedule_task_not_found(self, setup_db, mock_db):
        """Test error when task does not exist."""
        result = runner.invoke(
            app,
            [
                "schedule",
                "add",
                "--task",
                "nonexistent",
                "--cron",
                "0 * * * *",
            ],
        )

        assert result.exit_code == 1
        assert "Error:" in result.output
        assert "not found" in result.output.lower()

    def test_add_schedule_duplicate(self, setup_db, mock_db, sample_task):
        """Test error when creating duplicate schedule (same task + trigger type)."""
        # Create first schedule
        create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.CRON,
            {"cron": "0 * * * *"},
        )

        # Try to create duplicate
        result = runner.invoke(
            app,
            [
                "schedule",
                "add",
                "--task",
                "test-task",
                "--cron",
                "0 0 * * *",
            ],
        )

        assert result.exit_code == 1
        assert "Error:" in result.output
        assert "already exists" in result.output.lower()

    def test_add_schedule_invalid_cron(self, setup_db, mock_db, sample_task):
        """Test error with invalid cron expression."""
        result = runner.invoke(
            app,
            [
                "schedule",
                "add",
                "--task",
                "test-task",
                "--cron",
                "invalid",
            ],
        )

        assert result.exit_code == 1
        assert "Error:" in result.output
        assert "invalid" in result.output.lower()

    def test_add_schedule_invalid_interval_format(self, setup_db, mock_db, sample_task):
        """Test error with invalid interval format."""
        result = runner.invoke(
            app,
            [
                "schedule",
                "add",
                "--task",
                "test-task",
                "--every",
                "30x",
            ],
        )

        assert result.exit_code == 1
        assert "Error:" in result.output
        assert "invalid" in result.output.lower()

    def test_add_schedule_missing_trigger(self, setup_db, mock_db, sample_task):
        """Test error when no trigger type is specified."""
        result = runner.invoke(
            app,
            [
                "schedule",
                "add",
                "--task",
                "test-task",
            ],
        )

        assert result.exit_code == 1
        assert "Error:" in result.output
        assert "must specify" in result.output.lower()

    def test_add_schedule_multiple_triggers(self, setup_db, mock_db, sample_task):
        """Test error when multiple trigger types are specified."""
        result = runner.invoke(
            app,
            [
                "schedule",
                "add",
                "--task",
                "test-task",
                "--cron",
                "0 * * * *",
                "--every",
                "30m",
            ],
        )

        assert result.exit_code == 1
        assert "Error:" in result.output
        assert "multiple" in result.output.lower()


class TestScheduleList:
    """Tests for the 'schedule list' command."""

    def test_list_empty(self, setup_db, mock_db):
        """Test listing when no schedules exist."""
        result = runner.invoke(app, ["schedule", "list"])

        assert result.exit_code == 0
        assert "No schedules found" in result.stdout

    def test_list_all_schedules(self, setup_db, mock_db, sample_task):
        """Test listing all schedules."""
        # Create multiple schedules
        create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.CRON,
            {"cron": "0 * * * *"},
        )
        create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.INTERVAL,
            {"interval": {"minutes": 30}},
        )

        result = runner.invoke(app, ["schedule", "list"])

        assert result.exit_code == 0
        assert "Task Schedules" in result.stdout
        assert "test-task" in result.stdout
        assert "cron: 0 * * * *" in result.stdout
        assert "interval: 30m" in result.stdout

    def test_list_filter_by_task(self, setup_db, mock_db):
        """Test listing schedules filtered by task name."""
        # Create two tasks
        task1 = create_task(mock_db, name="task1", command="echo 1")
        task2 = create_task(mock_db, name="task2", command="echo 2")

        # Create schedules for both
        create_schedule(mock_db, task1.id, TriggerType.CRON, {"cron": "0 * * * *"})
        create_schedule(mock_db, task2.id, TriggerType.CRON, {"cron": "0 0 * * *"})

        # Filter by task1
        result = runner.invoke(app, ["schedule", "list", "--task", "task1"])

        assert result.exit_code == 0
        assert "task1" in result.stdout
        assert "task2" not in result.stdout

    def test_list_filter_by_enabled(self, setup_db, mock_db, sample_task):
        """Test listing schedules filtered by enabled status."""
        # Create enabled and disabled schedules
        create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.CRON,
            {"cron": "0 * * * *"},
            enabled=True,
        )
        create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.INTERVAL,
            {"interval": {"minutes": 30}},
            enabled=False,
        )

        # Filter by enabled
        result = runner.invoke(app, ["schedule", "list", "--enabled"])

        assert result.exit_code == 0
        assert "cron: 0 * * * *" in result.stdout
        assert "interval: 30m" not in result.stdout

    def test_list_filter_by_disabled(self, setup_db, mock_db, sample_task):
        """Test listing schedules filtered by disabled status."""
        # Create enabled and disabled schedules
        create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.CRON,
            {"cron": "0 * * * *"},
            enabled=True,
        )
        create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.INTERVAL,
            {"interval": {"minutes": 30}},
            enabled=False,
        )

        # Filter by disabled
        result = runner.invoke(app, ["schedule", "list", "--disabled"])

        assert result.exit_code == 0
        assert "cron: 0 * * * *" not in result.stdout
        assert "interval: 30m" in result.stdout

    def test_list_table_formatting(self, setup_db, mock_db, sample_task):
        """Test that list output includes all expected columns."""
        create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.CRON,
            {"cron": "0 * * * *"},
        )

        result = runner.invoke(app, ["schedule", "list"])

        assert result.exit_code == 0
        # Check for column headers
        assert "ID" in result.stdout
        assert "Task Name" in result.stdout
        assert "Trigger" in result.stdout
        assert "Enabled" in result.stdout
        assert "Next Run" in result.stdout
        assert "Last Run" in result.stdout

    def test_list_nonexistent_task_filter(self, setup_db, mock_db):
        """Test error when filtering by nonexistent task."""
        result = runner.invoke(app, ["schedule", "list", "--task", "nonexistent"])

        assert result.exit_code == 1
        assert "Error:" in result.output
        assert "not found" in result.output.lower()


class TestScheduleShow:
    """Tests for the 'schedule show' command."""

    def test_show_full_id(self, setup_db, mock_db, sample_task):
        """Test showing schedule details by full UUID."""
        schedule = create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.CRON,
            {"cron": "0 * * * *"},
        )

        result = runner.invoke(app, ["schedule", "show", schedule.id])

        assert result.exit_code == 0
        assert "Schedule:" in result.stdout
        assert schedule.id in result.stdout
        assert "test-task" in result.stdout
        assert "cron" in result.stdout
        assert "0 * * * *" in result.stdout

    def test_show_short_id(self, setup_db, mock_db, sample_task):
        """Test showing schedule details by short ID (8 chars)."""
        schedule = create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.INTERVAL,
            {"interval": {"minutes": 30}},
        )

        short_id = schedule.id[:8]
        result = runner.invoke(app, ["schedule", "show", short_id])

        assert result.exit_code == 0
        assert "Schedule:" in result.stdout
        assert "test-task" in result.stdout
        assert "interval" in result.stdout
        assert "30" in result.stdout

    def test_show_not_found(self, setup_db, mock_db):
        """Test error when schedule does not exist."""
        result = runner.invoke(app, ["schedule", "show", "nonexistent"])

        assert result.exit_code == 1
        assert "Error:" in result.output
        assert "not found" in result.output.lower()

    def test_show_cron_trigger(self, setup_db, mock_db, sample_task):
        """Test formatted output for CRON trigger."""
        schedule = create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.CRON,
            {"cron": "0 0 * * *"},
        )

        result = runner.invoke(app, ["schedule", "show", schedule.id])

        assert result.exit_code == 0
        assert "Trigger Type: cron" in result.stdout
        assert '"cron": "0 0 * * *"' in result.stdout

    def test_show_interval_trigger(self, setup_db, mock_db, sample_task):
        """Test formatted output for INTERVAL trigger."""
        schedule = create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.INTERVAL,
            {"interval": {"hours": 2}},
        )

        result = runner.invoke(app, ["schedule", "show", schedule.id])

        assert result.exit_code == 0
        assert "Trigger Type: interval" in result.stdout
        assert '"hours": 2' in result.stdout

    def test_show_once_trigger(self, setup_db, mock_db, sample_task):
        """Test formatted output for ONCE trigger."""
        schedule = create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.ONCE,
            {"once": "2026-04-10T15:00:00"},
        )

        result = runner.invoke(app, ["schedule", "show", schedule.id])

        assert result.exit_code == 0
        assert "Trigger Type: once" in result.stdout
        assert "2026-04-10T15:00:00" in result.stdout


class TestScheduleEnable:
    """Tests for the 'schedule enable' command."""

    def test_enable_full_id(self, setup_db, mock_db, sample_task):
        """Test enabling a schedule by full UUID."""
        schedule = create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.CRON,
            {"cron": "0 * * * *"},
            enabled=False,
        )

        result = runner.invoke(app, ["schedule", "enable", schedule.id])

        assert result.exit_code == 0
        assert "enabled" in result.output.lower()
        assert "✓" in result.stdout

        # Verify in database
        mock_db.refresh(schedule)
        assert schedule.enabled is True

    def test_enable_short_id(self, setup_db, mock_db, sample_task):
        """Test enabling a schedule by short ID."""
        schedule = create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.CRON,
            {"cron": "0 * * * *"},
            enabled=False,
        )

        short_id = schedule.id[:8]
        result = runner.invoke(app, ["schedule", "enable", short_id])

        assert result.exit_code == 0
        assert "enabled" in result.output.lower()

        # Verify in database
        mock_db.refresh(schedule)
        assert schedule.enabled is True

    def test_enable_not_found(self, setup_db, mock_db):
        """Test error when schedule does not exist."""
        result = runner.invoke(app, ["schedule", "enable", "nonexistent"])

        assert result.exit_code == 1
        assert "Error:" in result.output
        assert "not found" in result.output.lower()

    def test_enable_already_enabled(self, setup_db, mock_db, sample_task):
        """Test enabling a schedule that is already enabled."""
        schedule = create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.CRON,
            {"cron": "0 * * * *"},
            enabled=True,
        )

        result = runner.invoke(app, ["schedule", "enable", schedule.id])

        assert result.exit_code == 0
        assert "enabled" in result.output.lower()

        # Verify still enabled
        mock_db.refresh(schedule)
        assert schedule.enabled is True


class TestScheduleDisable:
    """Tests for the 'schedule disable' command."""

    def test_disable_full_id(self, setup_db, mock_db, sample_task):
        """Test disabling a schedule by full UUID."""
        schedule = create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.CRON,
            {"cron": "0 * * * *"},
            enabled=True,
        )

        result = runner.invoke(app, ["schedule", "disable", schedule.id])

        assert result.exit_code == 0
        assert "disabled" in result.output.lower()
        assert "✓" in result.stdout

        # Verify in database
        mock_db.refresh(schedule)
        assert schedule.enabled is False

    def test_disable_short_id(self, setup_db, mock_db, sample_task):
        """Test disabling a schedule by short ID."""
        schedule = create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.CRON,
            {"cron": "0 * * * *"},
            enabled=True,
        )

        short_id = schedule.id[:8]
        result = runner.invoke(app, ["schedule", "disable", short_id])

        assert result.exit_code == 0
        assert "disabled" in result.output.lower()

        # Verify in database
        mock_db.refresh(schedule)
        assert schedule.enabled is False

    def test_disable_not_found(self, setup_db, mock_db):
        """Test error when schedule does not exist."""
        result = runner.invoke(app, ["schedule", "disable", "nonexistent"])

        assert result.exit_code == 1
        assert "Error:" in result.output
        assert "not found" in result.output.lower()

    def test_disable_already_disabled(self, setup_db, mock_db, sample_task):
        """Test disabling a schedule that is already disabled."""
        schedule = create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.CRON,
            {"cron": "0 * * * *"},
            enabled=False,
        )

        result = runner.invoke(app, ["schedule", "disable", schedule.id])

        assert result.exit_code == 0
        assert "disabled" in result.output.lower()

        # Verify still disabled
        mock_db.refresh(schedule)
        assert schedule.enabled is False


class TestScheduleRemove:
    """Tests for the 'schedule remove' command."""

    def test_remove_with_yes_flag(self, setup_db, mock_db, sample_task):
        """Test removing a schedule with --yes flag."""
        schedule = create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.CRON,
            {"cron": "0 * * * *"},
        )
        schedule_id = schedule.id

        result = runner.invoke(app, ["schedule", "remove", schedule_id, "--yes"])

        assert result.exit_code == 0
        assert "removed" in result.output.lower()
        assert "✓" in result.stdout

        # Verify deleted from database
        deleted = mock_db.query(Schedule).filter_by(id=schedule_id).first()
        assert deleted is None

    def test_remove_with_confirmation_yes(self, setup_db, mock_db, sample_task):
        """Test removing a schedule with confirmation prompt (yes)."""
        schedule = create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.CRON,
            {"cron": "0 * * * *"},
        )
        schedule_id = schedule.id

        # Provide 'y' as input to confirmation prompt
        result = runner.invoke(app, ["schedule", "remove", schedule_id], input="y\n")

        assert result.exit_code == 0
        assert "removed" in result.output.lower()

        # Verify deleted from database
        deleted = mock_db.query(Schedule).filter_by(id=schedule_id).first()
        assert deleted is None

    def test_remove_with_confirmation_no(self, setup_db, mock_db, sample_task):
        """Test canceling schedule removal when prompted."""
        schedule = create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.CRON,
            {"cron": "0 * * * *"},
        )
        schedule_id = schedule.id
        mock_db.commit()  # Ensure schedule is committed
        mock_db.refresh(schedule)  # Refresh to get the ID

        # Provide 'n' as input to confirmation prompt
        result = runner.invoke(app, ["schedule", "remove", schedule_id], input="n\n")

        assert result.exit_code == 0
        assert "Cancelled" in result.output

        # Verify NOT deleted from database
        mock_db.rollback()  # Rollback any pending changes
        still_exists = mock_db.query(Schedule).filter_by(id=schedule_id).first()
        assert still_exists is not None

    def test_remove_not_found(self, setup_db, mock_db):
        """Test error when schedule does not exist."""
        result = runner.invoke(app, ["schedule", "remove", "nonexistent", "--yes"])

        assert result.exit_code == 1
        assert "Error:" in result.output
        assert "not found" in result.output.lower()

    def test_remove_short_id(self, setup_db, mock_db, sample_task):
        """Test removing a schedule by short ID."""
        schedule = create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.CRON,
            {"cron": "0 * * * *"},
        )
        schedule_id = schedule.id
        short_id = schedule_id[:8]

        result = runner.invoke(app, ["schedule", "remove", short_id, "--yes"])

        assert result.exit_code == 0
        assert "removed" in result.output.lower()

        # Verify deleted from database
        deleted = mock_db.query(Schedule).filter_by(id=schedule_id).first()
        assert deleted is None

    def test_remove_short_flag_alias(self, setup_db, mock_db, sample_task):
        """Test removing a schedule with -y short flag."""
        schedule = create_schedule(
            mock_db,
            sample_task.id,
            TriggerType.CRON,
            {"cron": "0 * * * *"},
        )
        schedule_id = schedule.id

        result = runner.invoke(app, ["schedule", "remove", schedule_id, "-y"])

        assert result.exit_code == 0
        assert "removed" in result.output.lower()

        # Verify deleted from database
        deleted = mock_db.query(Schedule).filter_by(id=schedule_id).first()
        assert deleted is None
