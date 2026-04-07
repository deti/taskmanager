---
crew: persistence
at_commit: 8194a9c
affected_partners: [task-service]
severity: major
acknowledged_by: []
---

# Builtin Plugins Implemented — Executor Integration Required

## Summary
Implemented retry and timeout builtin plugins. The timeout plugin requires executor modifications to honor `run.timeout_override`.

## What Changed

### New Files
- `src/taskmanager/plugins/builtin/__init__.py` — Package exports
- `src/taskmanager/plugins/builtin/retry.py` — RetryPlugin implementation
- `src/taskmanager/plugins/builtin/timeout.py` — TimeoutPlugin implementation
- `pyproject.toml` — Registered plugins as entry_points

### Plugin Behavior

**RetryPlugin** (`on_after_execute` hook):
- Triggered after task execution completes
- Only acts on failed runs (`run.status == RunStatus.FAILED`)
- Reads `task.task_metadata['retry_count']` to determine max retries
- Tracks retry attempts by counting failed runs in database
- Implements exponential backoff: `sleep(2 ** attempt)` seconds (1s, 2s, 4s, 8s, ...)
- Creates new Run record and calls `execute_task(task, db)` for each retry
- Stops when max retries reached or task succeeds

**TimeoutPlugin** (`on_before_execute` hook):
- Triggered before task execution starts
- Reads `task.task_metadata['timeout_seconds']` to override default timeout
- Sets `run.timeout_override` (dynamic attribute, not persisted) with the timeout value
- Returns True to allow execution

## Integration Required

The **executor** needs to be modified to honor `run.timeout_override`:

**File**: `src/taskmanager/executor.py`

**Location**: Line 159-161 (in `execute_task` function, before calling `_execute_subprocess`)

**Current code**:
```python
exit_code, stdout, stderr, duration_ms = _execute_subprocess(
    task.command, task.shell, settings.subprocess_timeout
)
```

**Required change**:
```python
# Check for timeout override from plugins (e.g., TimeoutPlugin)
timeout = getattr(run, "timeout_override", settings.subprocess_timeout)
exit_code, stdout, stderr, duration_ms = _execute_subprocess(
    task.command, task.shell, timeout
)
```

**Note**: The timeout plugin sets `run.timeout_override` as a dynamic attribute using Python's dynamic attribute system. This won't be persisted to the database, but will be available during the execution lifecycle.

## Testing Notes

Both plugins are discovered and loaded successfully:
```bash
uv run python -c "from taskmanager.plugins import PluginManager; pm = PluginManager(); print([p['name'] for p in pm.list_plugins()])"
# Output: ['retry', 'timeout']
```

Test scenarios for task-service crew (Wave 3 of plan):
1. **Retry**: Create task with `task_metadata={'retry_count': 3}`, use failing command, verify retries with backoff
2. **Timeout**: Create task with `task_metadata={'timeout_seconds': 5}`, use `sleep 999` command, verify timeout after 5s
3. **Combined**: Task with both retry and timeout metadata

## Priority
**High** — The plugins are implemented but non-functional until executor integration is complete.
