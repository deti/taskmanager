"""Task executor — runs shell commands and records execution results.

This module provides the core execution logic for running task commands
in subprocesses and capturing their output, exit codes, and execution metadata.
"""

import subprocess
import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from taskmanager.models import Run, RunStatus, Task
from taskmanager.settings import get_settings


def execute_task(task: Task, db: Session) -> Run:
    """Execute a task's command and record the run in the database.

    Creates a Run record with RUNNING status, executes the command via subprocess,
    captures stdout/stderr/exit_code, calculates duration, and updates the Run
    status to SUCCESS or FAILED based on the exit code.

    Parameters
    ----------
    task:
        The Task to execute. The command is captured as a snapshot before execution.
    db:
        SQLAlchemy session for database operations. Used to persist the Run record.

    Returns
    -------
    Run
        The completed Run object with execution results (status, exit_code,
        stdout, stderr, duration_ms).

    Notes
    -----
    - Timeout is configured via settings.subprocess_timeout (default: 300s)
    - On timeout, status is set to FAILED with an error_message
    - Command snapshot is frozen at execution time (not affected by later Task edits)
    - Duration is measured in milliseconds with high precision
    """
    settings = get_settings()

    # Create Run record with RUNNING status
    run = Run(
        task_id=task.id,
        status=RunStatus.RUNNING,
        command_snapshot=task.command,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()  # Persist to get the ID

    # Execute the command
    start_time = time.perf_counter()

    try:
        result = subprocess.run(
            task.command,
            shell=True,
            executable=task.shell,
            capture_output=True,
            text=True,
            timeout=settings.subprocess_timeout,
            check=False,  # Don't raise on non-zero exit codes
        )

        end_time = time.perf_counter()
        duration_ms = int((end_time - start_time) * 1000)

        # Update Run with results
        run.exit_code = result.returncode
        run.stdout = result.stdout
        run.stderr = result.stderr
        run.duration_ms = duration_ms
        run.finished_at = datetime.now(UTC)

        if result.returncode == 0:
            run.status = RunStatus.SUCCESS
        else:
            run.status = RunStatus.FAILED

    except subprocess.TimeoutExpired:
        end_time = time.perf_counter()
        duration_ms = int((end_time - start_time) * 1000)

        run.status = RunStatus.FAILED
        run.duration_ms = duration_ms
        run.finished_at = datetime.now(UTC)
        run.error_message = (
            f"Command timed out after {settings.subprocess_timeout} seconds"
        )

    except Exception as e:
        end_time = time.perf_counter()
        duration_ms = int((end_time - start_time) * 1000)

        run.status = RunStatus.FAILED
        run.duration_ms = duration_ms
        run.finished_at = datetime.now(UTC)
        run.error_message = f"Execution error: {type(e).__name__}: {e}"

    # Commit to database
    db.commit()

    return run
