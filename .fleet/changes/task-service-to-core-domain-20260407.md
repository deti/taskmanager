---
crew: task-service
at_commit: 912e616
affected_partners: [core-domain]
severity: minor
acknowledged_by: [cli, core-domain, api]
---

# TaskNotFoundError Type Signature Issue

## Summary
TaskNotFoundError.__init__ currently expects `task_id: int`, but the Task model uses UUID strings (`id: Mapped[str]`). This creates a type mismatch that requires `type: ignore` comments in the service layer.

## Impact
- Service layer functions (get_task, update_task, delete_task) all raise TaskNotFoundError with string UUIDs
- Added `type: ignore[arg-type]` comment in task_service.py:89 as workaround
- Code works at runtime (Python doesn't enforce type hints), but fails strict mypy checking without the ignore comment

## Suggested Fix
Update `TaskNotFoundError.__init__` signature to accept either int or str:

```python
def __init__(self, task_id: int | str) -> None:
    """Initialize the exception.

    Args:
        task_id: The ID of the task that was not found (int or UUID string).
    """
    self.task_id = task_id
    self.message = f"Task with ID {task_id} not found"
    super().__init__(self.message)
```

## Files Affected
- src/taskmanager/exceptions.py (owned by core-domain)
- src/taskmanager/services/task_service.py (workaround added)

## Priority
Low - workaround is in place and code functions correctly. This is a type annotation issue only.
