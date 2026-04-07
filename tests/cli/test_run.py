"""Tests for run CLI commands."""

from datetime import UTC, datetime

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

    monkeypatch.setattr("taskmanager.cli.run.get_db", _get_test_db)
    return db_session


@pytest.fixture
def sample_task(mock_db):
    """Create a sample task for testing."""
    return create_task(mock_db, name="test_task", command="echo hello")


@pytest.fixture
def sample_runs(mock_db, sample_task):
    """Create sample run data for testing."""
    runs = []

    # Create a successful run
    run1 = Run(
        task_id=sample_task.id,
        status=RunStatus.SUCCESS,
        command_snapshot="echo hello",
        started_at=datetime(2026, 4, 7, 10, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 4, 7, 10, 0, 1, tzinfo=UTC),
        exit_code=0,
        stdout="hello\n",
        stderr="",
        duration_ms=1000,
    )
    mock_db.add(run1)
    runs.append(run1)

    # Create a failed run
    run2 = Run(
        task_id=sample_task.id,
        status=RunStatus.FAILED,
        command_snapshot="exit 1",
        started_at=datetime(2026, 4, 7, 10, 1, 0, tzinfo=UTC),
        finished_at=datetime(2026, 4, 7, 10, 1, 1, tzinfo=UTC),
        exit_code=1,
        stdout="",
        stderr="error message\n",
        duration_ms=500,
    )
    mock_db.add(run2)
    runs.append(run2)

    # Create a running run
    run3 = Run(
        task_id=sample_task.id,
        status=RunStatus.RUNNING,
        command_snapshot="sleep 100",
        started_at=datetime(2026, 4, 7, 10, 2, 0, tzinfo=UTC),
    )
    mock_db.add(run3)
    runs.append(run3)

    mock_db.commit()

    # Refresh to get IDs
    for run in runs:
        mock_db.refresh(run)

    return runs


class TestRunList:
    """Tests for the 'run list' command."""

    def test_list_all_runs(self, setup_db, mock_db, sample_runs):
        """Test listing all runs without filters."""
        result = runner.invoke(app, ["run", "list"])

        assert result.exit_code == 0
        # Check that table is displayed
        assert "Task Execution Runs" in result.stdout
        # Check that all runs are shown (most recent first)
        for run in sample_runs:
            assert run.id[:8] in result.stdout

    def test_list_filter_by_task(self, setup_db, mock_db, sample_runs, sample_task):
        """Test filtering runs by task name."""
        result = runner.invoke(app, ["run", "list", "--task", "test_task"])

        assert result.exit_code == 0
        assert "Task Execution Runs" in result.stdout
        # All sample runs belong to test_task
        for run in sample_runs:
            assert run.id[:8] in result.stdout

    def test_list_filter_by_status_success(self, setup_db, mock_db, sample_runs):
        """Test filtering runs by status (success)."""
        result = runner.invoke(app, ["run", "list", "--status", "success"])

        assert result.exit_code == 0
        # Should show only the successful run
        assert sample_runs[0].id[:8] in result.stdout
        # Should not show failed or running runs
        assert sample_runs[1].id[:8] not in result.stdout
        assert sample_runs[2].id[:8] not in result.stdout

    def test_list_filter_by_status_failed(self, setup_db, mock_db, sample_runs):
        """Test filtering runs by status (failed)."""
        result = runner.invoke(app, ["run", "list", "--status", "failed"])

        assert result.exit_code == 0
        # Should show only the failed run
        assert sample_runs[1].id[:8] in result.stdout
        # Should not show success or running runs
        assert sample_runs[0].id[:8] not in result.stdout
        assert sample_runs[2].id[:8] not in result.stdout

    def test_list_filter_by_status_running(self, setup_db, mock_db, sample_runs):
        """Test filtering runs by status (running)."""
        result = runner.invoke(app, ["run", "list", "--status", "running"])

        assert result.exit_code == 0
        # Should show only the running run
        assert sample_runs[2].id[:8] in result.stdout
        # Should not show success or failed runs
        assert sample_runs[0].id[:8] not in result.stdout
        assert sample_runs[1].id[:8] not in result.stdout

    def test_list_with_limit(self, setup_db, mock_db, sample_runs):
        """Test limiting the number of runs displayed."""
        result = runner.invoke(app, ["run", "list", "--limit", "2"])

        assert result.exit_code == 0
        # Should show at most 2 runs
        # Count how many run IDs appear in output
        run_count = sum(1 for run in sample_runs if run.id[:8] in result.stdout)
        assert run_count <= 2

    def test_list_empty_results(self, setup_db, mock_db):
        """Test listing when no runs exist."""
        result = runner.invoke(app, ["run", "list"])

        assert result.exit_code == 0
        assert "No runs found" in result.stdout

    def test_list_invalid_status(self, setup_db, mock_db):
        """Test filtering with an invalid status."""
        result = runner.invoke(app, ["run", "list", "--status", "invalid"])

        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "Error:" in output
        assert "Invalid status" in output

    def test_list_nonexistent_task(self, setup_db, mock_db):
        """Test filtering by a task that doesn't exist."""
        result = runner.invoke(app, ["run", "list", "--task", "nonexistent"])

        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "Error:" in output
        assert "not found" in output

    def test_list_table_formatting(self, setup_db, mock_db, sample_runs):
        """Test that the table contains expected columns."""
        result = runner.invoke(app, ["run", "list"])

        assert result.exit_code == 0
        # Check for column headers
        assert "ID" in result.stdout
        assert "Task" in result.stdout
        assert "Status" in result.stdout
        assert "Duration" in result.stdout
        assert "Started At" in result.stdout

    def test_list_inline_run(self, setup_db, mock_db):
        """Test listing inline runs (task_id is None)."""
        # Create an inline run
        inline_run = Run(
            task_id=None,
            status=RunStatus.SUCCESS,
            command_snapshot="echo inline",
            started_at=datetime(2026, 4, 7, 10, 0, 0, tzinfo=UTC),
            finished_at=datetime(2026, 4, 7, 10, 0, 1, tzinfo=UTC),
            exit_code=0,
            stdout="inline\n",
            stderr="",
            duration_ms=1000,
        )
        mock_db.add(inline_run)
        mock_db.commit()
        mock_db.refresh(inline_run)

        result = runner.invoke(app, ["run", "list"])

        assert result.exit_code == 0
        # Check that the inline run is displayed with "(inline)" in Task column
        assert inline_run.id[:8] in result.stdout
        assert "(inline)" in result.stdout

    def test_list_mixed_runs(self, setup_db, mock_db, sample_task):
        """Test listing both task-based and inline runs together."""
        # Create a task-based run
        task_run = Run(
            task_id=sample_task.id,
            status=RunStatus.SUCCESS,
            command_snapshot="echo task",
            started_at=datetime(2026, 4, 7, 10, 0, 0, tzinfo=UTC),
            finished_at=datetime(2026, 4, 7, 10, 0, 1, tzinfo=UTC),
            exit_code=0,
            stdout="task\n",
            stderr="",
            duration_ms=1000,
        )
        mock_db.add(task_run)

        # Create an inline run
        inline_run = Run(
            task_id=None,
            status=RunStatus.SUCCESS,
            command_snapshot="echo inline",
            started_at=datetime(2026, 4, 7, 10, 1, 0, tzinfo=UTC),
            finished_at=datetime(2026, 4, 7, 10, 1, 1, tzinfo=UTC),
            exit_code=0,
            stdout="inline\n",
            stderr="",
            duration_ms=1000,
        )
        mock_db.add(inline_run)
        mock_db.commit()
        mock_db.refresh(task_run)
        mock_db.refresh(inline_run)

        result = runner.invoke(app, ["run", "list"])

        assert result.exit_code == 0
        # Both runs should be displayed
        assert task_run.id[:8] in result.stdout
        assert inline_run.id[:8] in result.stdout
        # Task-based run should show task name
        assert "test_task" in result.stdout
        # Inline run should show "(inline)"
        assert "(inline)" in result.stdout


class TestRunShow:
    """Tests for the 'run show' command."""

    def test_show_with_full_uuid(self, setup_db, mock_db, sample_runs):
        """Test showing a run with full UUID."""
        run = sample_runs[0]
        result = runner.invoke(app, ["run", "show", run.id])

        assert result.exit_code == 0
        # Check that all expected fields are displayed
        assert run.id in result.stdout
        assert "test_task" in result.stdout
        assert "success" in result.stdout
        assert "echo hello" in result.stdout
        assert "Exit Code:" in result.stdout
        assert "0" in result.stdout
        assert "Duration:" in result.stdout

    def test_show_with_short_id(self, setup_db, mock_db, sample_runs):
        """Test showing a run with short ID (first 8 chars)."""
        run = sample_runs[0]
        short_id = run.id[:8]
        result = runner.invoke(app, ["run", "show", short_id])

        assert result.exit_code == 0
        # Should display the full run details
        assert run.id in result.stdout
        assert "test_task" in result.stdout

    def test_show_failed_run_with_error(self, setup_db, mock_db, sample_runs):
        """Test showing a failed run (displays error message if present)."""
        run = sample_runs[1]
        # Add an error message
        run.error_message = "Command failed with exit code 1"
        mock_db.commit()

        result = runner.invoke(app, ["run", "show", run.id])

        assert result.exit_code == 0
        assert "failed" in result.stdout
        assert "Error:" in result.stdout
        assert "Command failed with exit code 1" in result.stdout

    def test_show_run_not_found(self, setup_db, mock_db):
        """Test showing a run that doesn't exist."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        result = runner.invoke(app, ["run", "show", fake_id])

        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "Error:" in output
        assert "not found" in output

    def test_show_output_contains_all_fields(self, setup_db, mock_db, sample_runs):
        """Test that show output contains all expected fields."""
        run = sample_runs[0]
        result = runner.invoke(app, ["run", "show", run.id])

        assert result.exit_code == 0
        # Check for all expected field labels
        assert "Run:" in result.stdout
        assert "Task:" in result.stdout
        assert "Status:" in result.stdout
        assert "Command:" in result.stdout
        assert "Exit Code:" in result.stdout
        assert "Duration:" in result.stdout
        assert "Started At:" in result.stdout
        assert "Finished At:" in result.stdout

    def test_show_inline_run(self, setup_db, mock_db):
        """Test showing an inline run (task_id is None)."""
        # Create an inline run
        inline_run = Run(
            task_id=None,
            status=RunStatus.SUCCESS,
            command_snapshot="echo inline",
            started_at=datetime(2026, 4, 7, 10, 0, 0, tzinfo=UTC),
            finished_at=datetime(2026, 4, 7, 10, 0, 1, tzinfo=UTC),
            exit_code=0,
            stdout="inline\n",
            stderr="",
            duration_ms=1000,
        )
        mock_db.add(inline_run)
        mock_db.commit()
        mock_db.refresh(inline_run)

        result = runner.invoke(app, ["run", "show", inline_run.id])

        assert result.exit_code == 0
        # Check that inline run displays "(inline)" for task name
        assert inline_run.id in result.stdout
        assert "Task: (inline)" in result.stdout
        assert "echo inline" in result.stdout
        assert "success" in result.stdout


class TestRunExec:
    """Tests for the 'run exec' command."""

    def test_exec_success(self, setup_db, mock_db):
        """Test inline execution success."""
        result = runner.invoke(app, ["run", "exec", "echo hello"])

        assert result.exit_code == 0
        # Check stdout section contains "hello"
        assert "hello" in result.stdout
        # Check that run ID is displayed
        assert "Run ID:" in result.stdout
        # Check success message
        assert "Command completed successfully" in result.stdout
        assert "exit code: 0" in result.stdout

    def test_exec_failure(self, setup_db, mock_db):
        """Test inline execution failure."""
        result = runner.invoke(app, ["run", "exec", "exit 1"])

        assert result.exit_code == 1
        # Check failure message
        assert "Command failed" in result.stdout
        assert "exit code: 1" in result.stdout

    def test_exec_with_stderr(self, setup_db, mock_db):
        """Test inline execution with stderr."""
        # Use a shell command that writes to stderr
        result = runner.invoke(app, ["run", "exec", "sh -c 'echo error >&2'"])

        # Command may succeed with exit code 0
        assert "STDERR:" in result.stdout
        assert "error" in result.stdout

    def test_exec_appears_in_list(self, setup_db, mock_db):
        """Test inline run appears in list with (inline) marker."""
        # Execute an inline command
        exec_result = runner.invoke(app, ["run", "exec", "echo test"])
        assert exec_result.exit_code == 0

        # List all runs
        list_result = runner.invoke(app, ["run", "list"])

        assert list_result.exit_code == 0
        # Check that inline run appears with "(inline)" marker
        assert "(inline)" in list_result.stdout

    def test_exec_in_show_command(self, setup_db, mock_db):
        """Test inline run appears correctly in show command."""
        # Execute an inline command and capture run ID
        exec_result = runner.invoke(app, ["run", "exec", "echo show_test"])
        assert exec_result.exit_code == 0

        # Extract run ID from output (format: "Run ID: <8-char-id>")
        import re
        match = re.search(r"Run ID: ([a-f0-9]{8})", exec_result.stdout)
        assert match is not None
        run_id = match.group(1)

        # Show the run
        show_result = runner.invoke(app, ["run", "show", run_id])

        assert show_result.exit_code == 0
        # Check that task is displayed as "(inline)"
        assert "Task: (inline)" in show_result.stdout
        # Check that command snapshot is displayed
        assert "echo show_test" in show_result.stdout


class TestRunLogs:
    """Tests for the 'run logs' command."""

    def test_logs_with_stdout_only(self, setup_db, mock_db, sample_runs):
        """Test displaying logs with stdout only."""
        run = sample_runs[0]  # This run has stdout
        result = runner.invoke(app, ["run", "logs", run.id])

        assert result.exit_code == 0
        assert "=== STDOUT ===" in result.stdout
        assert "hello" in result.stdout
        assert "=== STDERR ===" in result.stdout
        assert "(empty)" in result.stdout

    def test_logs_with_stderr_only(self, setup_db, mock_db, sample_runs):
        """Test displaying logs with stderr only."""
        run = sample_runs[1]  # This run has stderr
        result = runner.invoke(app, ["run", "logs", run.id])

        assert result.exit_code == 0
        assert "=== STDOUT ===" in result.stdout
        assert "=== STDERR ===" in result.stdout
        assert "error message" in result.stdout

    def test_logs_with_both_stdout_and_stderr(self, setup_db, mock_db, sample_task):
        """Test displaying logs with both stdout and stderr."""
        # Create a run with both stdout and stderr
        run = Run(
            task_id=sample_task.id,
            status=RunStatus.SUCCESS,
            command_snapshot="test command",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            exit_code=0,
            stdout="standard output\n",
            stderr="standard error\n",
            duration_ms=100,
        )
        mock_db.add(run)
        mock_db.commit()
        mock_db.refresh(run)

        result = runner.invoke(app, ["run", "logs", run.id])

        assert result.exit_code == 0
        assert "=== STDOUT ===" in result.stdout
        assert "standard output" in result.stdout
        assert "=== STDERR ===" in result.stdout
        assert "standard error" in result.stdout

    def test_logs_with_empty_output(self, setup_db, mock_db, sample_task):
        """Test displaying logs with empty output (shows '(empty)')."""
        # Create a run with no output
        run = Run(
            task_id=sample_task.id,
            status=RunStatus.SUCCESS,
            command_snapshot="test command",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            exit_code=0,
            stdout="",
            stderr="",
            duration_ms=100,
        )
        mock_db.add(run)
        mock_db.commit()
        mock_db.refresh(run)

        result = runner.invoke(app, ["run", "logs", run.id])

        assert result.exit_code == 0
        # Both stdout and stderr should show (empty)
        output_empty_count = result.stdout.count("(empty)")
        assert output_empty_count == 2

    def test_logs_with_short_id(self, setup_db, mock_db, sample_runs):
        """Test displaying logs with short ID matching."""
        run = sample_runs[0]
        short_id = run.id[:8]
        result = runner.invoke(app, ["run", "logs", short_id])

        assert result.exit_code == 0
        assert "=== STDOUT ===" in result.stdout
        assert "=== STDERR ===" in result.stdout

    def test_logs_run_not_found(self, setup_db, mock_db):
        """Test displaying logs for a run that doesn't exist."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        result = runner.invoke(app, ["run", "logs", fake_id])

        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "Error:" in output
        assert "not found" in output
