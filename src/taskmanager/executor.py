"""Task executor — runs shell commands and records execution results.

This module provides the core execution logic for running task commands
in subprocesses and capturing their output, exit codes, and execution metadata.

This module provides two execution modes:
- execute_task: Executes a registered Task object (Run.task_id is set)
- execute_inline: Executes an ad-hoc command string (Run.task_id is None)
"""

import subprocess
import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from taskmanager.logging import get_logger
from taskmanager.models import Run, RunStatus, Task
from taskmanager.settings import get_settings


logger = get_logger(__name__)


def _execute_subprocess(
    command: str, shell: str, timeout: int
) -> tuple[int, str, str, int]:
    """Execute a shell command via subprocess and capture results.

    This is a private helper function that contains the common subprocess
    execution logic used by both execute_task and execute_inline.

    Parameters
    ----------
    command:
        The shell command to execute.
    shell:
        The shell executable to use (e.g., /bin/sh, /bin/bash).
    timeout:
        Maximum execution time in seconds.

    Returns
    -------
    tuple[int, str, str, int]
        A tuple containing (exit_code, stdout, stderr, duration_ms).

    Raises
    ------
    subprocess.TimeoutExpired
        If the command exceeds the timeout.
    Exception
        For any other execution errors.
    """
    start_time = time.perf_counter()

    result = subprocess.run(
        command,
        shell=True,
        executable=shell,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,  # Don't raise on non-zero exit codes
    )

    end_time = time.perf_counter()
    duration_ms = int((end_time - start_time) * 1000)

    return result.returncode, result.stdout, result.stderr, duration_ms


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

    logger.info(
        "task.executing",
        task_name=task.name,
        task_id=task.id,
        run_id=run.id,
    )

    # Execute the command
    start_time = time.perf_counter()

    try:
        exit_code, stdout, stderr, duration_ms = _execute_subprocess(
            task.command, task.shell, settings.subprocess_timeout
        )

        # Update Run with results
        run.exit_code = exit_code
        run.stdout = stdout
        run.stderr = stderr
        run.duration_ms = duration_ms
        run.finished_at = datetime.now(UTC)

        if exit_code == 0:
            run.status = RunStatus.SUCCESS
            logger.info(
                "task.completed",
                task_name=task.name,
                task_id=task.id,
                run_id=run.id,
                exit_code=exit_code,
                duration_ms=duration_ms,
                status="success",
            )
        else:
            run.status = RunStatus.FAILED
            logger.warning(
                "task.failed",
                task_name=task.name,
                task_id=task.id,
                run_id=run.id,
                exit_code=exit_code,
                duration_ms=duration_ms,
                status="failed",
            )

    except subprocess.TimeoutExpired:
        end_time = time.perf_counter()
        duration_ms = int((end_time - start_time) * 1000)

        run.status = RunStatus.FAILED
        run.duration_ms = duration_ms
        run.finished_at = datetime.now(UTC)
        run.error_message = (
            f"Command timed out after {settings.subprocess_timeout} seconds"
        )

        logger.exception(
            "task.timeout",
            task_name=task.name,
            task_id=task.id,
            run_id=run.id,
            duration_ms=duration_ms,
            timeout=settings.subprocess_timeout,
            status="timeout",
        )

    except Exception as e:
        end_time = time.perf_counter()
        duration_ms = int((end_time - start_time) * 1000)

        run.status = RunStatus.FAILED
        run.duration_ms = duration_ms
        run.finished_at = datetime.now(UTC)
        run.error_message = f"Execution error: {type(e).__name__}: {e}"

        logger.exception(
            "task.failed",
            task_name=task.name,
            task_id=task.id,
            run_id=run.id,
            error=str(e),
            error_type=type(e).__name__,
            status="failed",
        )

    # Commit to database
    db.commit()

    return run


def execute_inline(command: str, db: Session, shell: str = "/bin/sh") -> Run:
    """Execute an ad-hoc command and record the run in the database.

    This function executes a one-off command without requiring a registered Task.
    The Run record is created with task_id=None to distinguish it from task-based
    executions.

    Parameters
    ----------
    command:
        The shell command to execute. This is captured as a snapshot in the Run.
    db:
        SQLAlchemy session for database operations. Used to persist the Run record.
    shell:
        The shell executable to use. Defaults to /bin/sh (same as Task.shell default).

    Returns
    -------
    Run
        The completed Run object with execution results (status, exit_code,
        stdout, stderr, duration_ms). Run.task_id will be None.

    Notes
    -----
    - Timeout is configured via settings.subprocess_timeout (default: 300s)
    - On timeout, status is set to FAILED with an error_message
    - Duration is measured in milliseconds with high precision
    - This function shares the same subprocess execution logic as execute_task

    Differences from execute_task:
    - execute_task: executes a registered Task object (Run.task_id is set)
    - execute_inline: executes an ad-hoc command string (Run.task_id is None)
    """
    settings = get_settings()

    # Create Run record with RUNNING status and task_id=None
    run = Run(
        task_id=None,  # Nullable FK for inline runs
        status=RunStatus.RUNNING,
        command_snapshot=command,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()  # Persist to get the ID

    logger.info(
        "task.executing",
        task_name="<inline>",
        task_id=None,
        run_id=run.id,
    )

    # Execute the command
    start_time = time.perf_counter()

    try:
        exit_code, stdout, stderr, duration_ms = _execute_subprocess(
            command, shell, settings.subprocess_timeout
        )

        # Update Run with results
        run.exit_code = exit_code
        run.stdout = stdout
        run.stderr = stderr
        run.duration_ms = duration_ms
        run.finished_at = datetime.now(UTC)

        if exit_code == 0:
            run.status = RunStatus.SUCCESS
            logger.info(
                "task.completed",
                task_name="<inline>",
                task_id=None,
                run_id=run.id,
                exit_code=exit_code,
                duration_ms=duration_ms,
                status="success",
            )
        else:
            run.status = RunStatus.FAILED
            logger.warning(
                "task.failed",
                task_name="<inline>",
                task_id=None,
                run_id=run.id,
                exit_code=exit_code,
                duration_ms=duration_ms,
                status="failed",
            )

    except subprocess.TimeoutExpired:
        end_time = time.perf_counter()
        duration_ms = int((end_time - start_time) * 1000)

        run.status = RunStatus.FAILED
        run.duration_ms = duration_ms
        run.finished_at = datetime.now(UTC)
        run.error_message = (
            f"Command timed out after {settings.subprocess_timeout} seconds"
        )

        logger.exception(
            "task.timeout",
            task_name="<inline>",
            task_id=None,
            run_id=run.id,
            duration_ms=duration_ms,
            timeout=settings.subprocess_timeout,
            status="timeout",
        )

    except Exception as e:
        end_time = time.perf_counter()
        duration_ms = int((end_time - start_time) * 1000)

        run.status = RunStatus.FAILED
        run.duration_ms = duration_ms
        run.finished_at = datetime.now(UTC)
        run.error_message = f"Execution error: {type(e).__name__}: {e}"

        logger.exception(
            "task.failed",
            task_name="<inline>",
            task_id=None,
            run_id=run.id,
            error=str(e),
            error_type=type(e).__name__,
            status="failed",
        )

    # Commit to database
    db.commit()

    return run
