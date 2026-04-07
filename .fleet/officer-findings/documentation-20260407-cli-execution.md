---
officer: documentation
plan: 2026-04-07-cli-execution-commands
reviewed_at: 2026-04-07
severity: minor
status: needs_update
---

# Documentation Review: CLI Execution Commands

## Summary
Code is well-documented with docstrings, but CLAUDE.md needs updates to reflect the new CLI commands.

## Documentation Coverage

### Code Documentation

**Docstrings Present:**
- `src/taskmanager/services/run_service.py` - All functions have comprehensive docstrings
- `src/taskmanager/cli/run.py` - All commands have docstrings shown in CLI help
- `src/taskmanager/exceptions.py` - RunNotFoundError has proper docstring

**CLI Help Text:**
- All commands provide clear, concise help text
- Parameter descriptions present
- Examples could be added but not required for v1

### CLAUDE.md Updates Needed

**Current state:** CLAUDE.md documents the task management commands but does not mention:
1. `taskmanager task exec <name>` command
2. `taskmanager run` sub-app with list/show/logs commands
3. Database initialization requirement

**Recommended additions:**

```markdown
## Commands

```bash
# Task management
make serve         # Start API server (uvicorn on 127.0.0.1:8000)
make show-settings # Print current settings as JSON

# Task execution (new in F2.S2)
taskmanager task exec <name>        # Execute a task and record run
taskmanager run list                # List task runs
taskmanager run list --status failed # Filter by status
taskmanager run list --task <name>  # Filter by task name
taskmanager run show <run-id>       # Show run details
taskmanager run logs <run-id>       # Show run output

# Database initialization (required on first use)
uv run python -c "from taskmanager.database import get_engine, Base; from taskmanager.models import Task, Run; Base.metadata.create_all(get_engine())"
```
```

## Strengths

1. **Comprehensive Docstrings:** All service functions have full parameter and return documentation
2. **CLI Help:** Built-in help system provides good UX
3. **Code Comments:** Clear inline comments where needed (e.g., session context handling)

## Issues Found

**Minor:**
- CLAUDE.md doesn't document new CLI commands
- Database initialization step not documented anywhere

**Not an issue:**
- README (if it exists) would need updates, but CLAUDE.md is the primary developer documentation for this repo per the architecture

## Recommendations

1. **Update CLAUDE.md** with new command examples (see template above)
2. **Add DB initialization note** to setup section
3. **Future enhancement:** Consider creating a `taskmanager init` command to replace the manual Python command
4. **Future enhancement:** Add a CHANGELOG.md or update existing one with F2.S2 release notes

## Conclusion
Code documentation is excellent. Project documentation (CLAUDE.md) needs minor updates. This is not a blocking issue but should be addressed before the feature is considered complete.

**Recommendation:** Update CLAUDE.md with the new commands before final report.
