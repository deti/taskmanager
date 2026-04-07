#!/usr/bin/env python3
"""Verification script for timeout plugin integration.

This script tests that the timeout plugin override is correctly integrated
into the executor.
"""

import time

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from taskmanager.database import Base
from taskmanager.executor import execute_task
from taskmanager.models import RunStatus, Task


def test_timeout_override():
    """Test that timeout override from plugin is used."""
    # Create in-memory database
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)
    db = session_local()

    try:
        # Create task with 2-second timeout override
        task = Task(
            name="timeout-test",
            command="sleep 10",
            task_metadata={"timeout_seconds": 2},
        )
        db.add(task)
        db.commit()

        print(f"Created task: {task.name} (ID: {task.id})")
        print(f"Task metadata: {task.task_metadata}")

        # Execute — should timeout after 2s (not default 300s)
        start = time.perf_counter()
        run = execute_task(task, db)
        duration = time.perf_counter() - start

        print(f"\nExecution results:")
        print(f"Status: {run.status.value}")
        print(f"Duration: {run.duration_ms}ms (wall time: {duration:.2f}s)")
        print(f"Error: {run.error_message}")

        # Verify timeout override was used
        assert run.status == RunStatus.FAILED, f"Expected FAILED, got {run.status}"
        assert run.error_message is not None, "Expected error message"
        assert "2 seconds" in run.error_message, (
            f"Expected '2 seconds' in error message, got: {run.error_message}"
        )
        assert 1500 < run.duration_ms < 3000, (
            f"Expected ~2000ms duration, got {run.duration_ms}ms"
        )

        print("\n✅ Timeout override integration verified!")
    finally:
        db.close()


def test_no_metadata_uses_default():
    """Test that tasks without metadata use default timeout."""
    # Create in-memory database
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)
    db = session_local()

    try:
        # Create task without metadata
        task = Task(
            name="no-timeout-test",
            command="echo 'hello'",
        )
        db.add(task)
        db.commit()

        print(f"\nCreated task: {task.name} (ID: {task.id})")
        print(f"Task metadata: {task.task_metadata}")

        # Execute — should use default timeout (300s) but complete quickly
        run = execute_task(task, db)

        print(f"\nExecution results:")
        print(f"Status: {run.status.value}")
        print(f"Duration: {run.duration_ms}ms")
        print(f"Exit code: {run.exit_code}")

        # Verify success
        assert run.status == RunStatus.SUCCESS, f"Expected SUCCESS, got {run.status}"
        assert run.exit_code == 0, f"Expected exit code 0, got {run.exit_code}"

        print("\n✅ Default timeout behavior verified!")
    finally:
        db.close()


if __name__ == "__main__":
    print("=" * 70)
    print("TIMEOUT PLUGIN INTEGRATION VERIFICATION")
    print("=" * 70)

    test_timeout_override()
    test_no_metadata_uses_default()

    print("\n" + "=" * 70)
    print("ALL VERIFICATION TESTS PASSED")
    print("=" * 70)
