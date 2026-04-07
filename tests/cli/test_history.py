"""Tests for history CLI commands."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from taskmanager.cli import app
from taskmanager.database import Base
from taskmanager.models import Run, RunStatus
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

    monkeypatch.setattr("taskmanager.cli.history.get_db", _get_test_db)
    return db_session


@pytest.fixture
def sample_task(mock_db):
    """Create a sample task for testing."""
    return create_task(mock_db, name="test_task", command="echo hello")


@pytest.fixture
def sample_runs(mock_db, sample_task):
    """Create sample run data for testing."""
    runs = []
    # Use naive datetime since SQLite strips timezone info
    # This matches the reality of how SQLite stores datetimes
    now = datetime.now(UTC).replace(tzinfo=None)

    # Create old runs (older than 30 days)
    for i in range(3):
        run = Run(
            task_id=sample_task.id,
            status=RunStatus.SUCCESS,
            command_snapshot="echo old",
            started_at=now - timedelta(days=35 + i),
            finished_at=now - timedelta(days=35 + i, seconds=-1),
            exit_code=0,
            duration_ms=1000,
        )
        mock_db.add(run)
        runs.append(run)

    # Create recent runs
    for i in range(2):
        run = Run(
            task_id=sample_task.id,
            status=RunStatus.SUCCESS,
            command_snapshot="echo recent",
            started_at=now - timedelta(days=i),
            finished_at=now - timedelta(days=i, seconds=-1),
            exit_code=0,
            duration_ms=1500,
        )
        mock_db.add(run)
        runs.append(run)

    # Create a failed run
    run = Run(
        task_id=sample_task.id,
        status=RunStatus.FAILED,
        command_snapshot="exit 1",
        started_at=now - timedelta(days=1),
        finished_at=now - timedelta(days=1, seconds=-1),
        exit_code=1,
        duration_ms=500,
    )
    mock_db.add(run)
    runs.append(run)

    mock_db.commit()

    for run in runs:
        mock_db.refresh(run)

    return runs


def test_prune_with_older_than(setup_db, mock_db, sample_runs, monkeypatch):
    """Test prune command with --older-than option."""
    # Work around SQLite timezone-naive datetime storage
    # Mock datetime.now in history_service to return naive datetime
    from datetime import datetime as dt_class

    class MockDatetime:
        @staticmethod
        def now(tz=None):
            return dt_class.now(tz).replace(tzinfo=None) if tz else dt_class.now()

    monkeypatch.setattr("taskmanager.services.history_service.datetime", MockDatetime)

    result = runner.invoke(app, ["history", "prune", "--older-than", "30"])

    assert result.exit_code == 0, f"Exit code {result.exit_code}, output: {result.output}"
    assert "Deleted 3 runs" in result.output


def test_prune_dry_run(setup_db, mock_db, sample_runs):
    """Test prune command with --dry-run option."""
    result = runner.invoke(app, ["history", "prune", "--older-than", "30", "--dry-run"])

    assert result.exit_code == 0
    assert "Would delete 3 runs" in result.output


def test_prune_default_retention(setup_db, mock_db, sample_runs, monkeypatch):
    """Test prune command using default retention from settings."""
    # Work around SQLite timezone-naive datetime storage
    from datetime import datetime as dt_class

    class MockDatetime:
        @staticmethod
        def now(tz=None):
            return dt_class.now(tz).replace(tzinfo=None) if tz else dt_class.now()

    monkeypatch.setattr("taskmanager.services.history_service.datetime", MockDatetime)

    # Mock get_settings to return a specific retention period
    from taskmanager.settings import Settings

    mock_settings = Settings()
    mock_settings.history_retention_days = 30

    monkeypatch.setattr(
        "taskmanager.services.history_service.get_settings",
        lambda: mock_settings,
    )

    result = runner.invoke(app, ["history", "prune"])

    assert result.exit_code == 0
    assert "Deleted" in result.output


def test_stats_global(setup_db, mock_db, sample_runs):
    """Test stats command without task filter (global stats)."""
    result = runner.invoke(app, ["history", "stats"])

    assert result.exit_code == 0
    assert "Execution Statistics" in result.output
    assert "Total Runs" in result.output
    assert "Success Rate" in result.output
    assert "Avg Duration" in result.output
    # Check for the "6" total runs we created
    assert "6" in result.output


def test_stats_per_task(setup_db, mock_db, sample_runs, sample_task):
    """Test stats command with --task option."""
    result = runner.invoke(app, ["history", "stats", "--task", "test_task"])

    assert result.exit_code == 0
    assert "Execution Statistics" in result.output
    assert "Total Runs" in result.output
    assert "Success Rate" in result.output


def test_stats_task_not_found(setup_db, mock_db, sample_runs):
    """Test stats command with non-existent task."""
    result = runner.invoke(app, ["history", "stats", "--task", "nonexistent"])

    assert result.exit_code == 1
    assert "Error" in result.output
    assert "not found" in result.output


def test_stats_shows_most_failed_tasks(setup_db, mock_db, sample_task):
    """Test that global stats shows most failed tasks table."""
    # Create multiple tasks with varying failure counts
    task1 = create_task(mock_db, name="flaky_task", command="exit 1")
    task2 = create_task(mock_db, name="stable_task", command="echo ok")

    # Use naive datetime since SQLite strips timezone info
    now = datetime.now(UTC).replace(tzinfo=None)

    # Add 5 failures for flaky_task
    for i in range(5):
        run = Run(
            task_id=task1.id,
            status=RunStatus.FAILED,
            command_snapshot="exit 1",
            started_at=now - timedelta(hours=i),
            finished_at=now - timedelta(hours=i, seconds=-1),
            exit_code=1,
            duration_ms=100,
        )
        mock_db.add(run)

    # Add 1 failure for stable_task
    run = Run(
        task_id=task2.id,
        status=RunStatus.FAILED,
        command_snapshot="exit 1",
        started_at=now - timedelta(hours=1),
        finished_at=now - timedelta(hours=1, seconds=-1),
        exit_code=1,
        duration_ms=100,
    )
    mock_db.add(run)

    mock_db.commit()

    result = runner.invoke(app, ["history", "stats"])

    assert result.exit_code == 0
    assert "Top Failed Tasks" in result.output
    assert "flaky_task" in result.output
    assert "5" in result.output


def test_stats_no_failed_tasks(setup_db, mock_db, sample_task):
    """Test that stats doesn't show failed tasks table when there are no failures."""
    # Use naive datetime since SQLite strips timezone info
    now = datetime.now(UTC).replace(tzinfo=None)

    # Create only successful runs
    for i in range(3):
        run = Run(
            task_id=sample_task.id,
            status=RunStatus.SUCCESS,
            command_snapshot="echo ok",
            started_at=now - timedelta(hours=i),
            finished_at=now - timedelta(hours=i, seconds=-1),
            exit_code=0,
            duration_ms=1000,
        )
        mock_db.add(run)

    mock_db.commit()

    result = runner.invoke(app, ["history", "stats"])

    assert result.exit_code == 0
    assert "Execution Statistics" in result.output
    # Should not show failed tasks table
    assert "Top Failed Tasks" not in result.output


def test_stats_no_duration_data(setup_db, mock_db, sample_task):
    """Test stats display when no runs have duration data."""
    # Use naive datetime since SQLite strips timezone info
    now = datetime.now(UTC).replace(tzinfo=None)

    # Create runs without duration_ms
    run = Run(
        task_id=sample_task.id,
        status=RunStatus.SUCCESS,
        command_snapshot="echo ok",
        started_at=now,
        finished_at=now + timedelta(seconds=1),
        exit_code=0,
        duration_ms=None,  # No duration data
    )
    mock_db.add(run)
    mock_db.commit()

    result = runner.invoke(app, ["history", "stats"])

    assert result.exit_code == 0
    assert "Avg Duration" in result.output
    # Should show "-" when no duration data
    assert "-" in result.output


def test_prune_handles_service_error(setup_db, mock_db):
    """Test that prune command handles service errors gracefully."""
    with patch(
        "taskmanager.cli.history.history_service.prune_runs",
        side_effect=Exception("Database error"),
    ):
        result = runner.invoke(app, ["history", "prune", "--older-than", "30"])

        assert result.exit_code == 1
        assert "Error" in result.output


def test_stats_handles_service_error(setup_db, mock_db):
    """Test that stats command handles service errors gracefully."""
    with patch(
        "taskmanager.cli.history.history_service.get_stats",
        side_effect=Exception("Database error"),
    ):
        result = runner.invoke(app, ["history", "stats"])

        assert result.exit_code == 1
        assert "Error" in result.output
