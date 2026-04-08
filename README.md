# taskmanager

**A flexible task management and scheduling system with plugin support and structured logging.**

Taskmanager combines a FastAPI HTTP API with a powerful CLI for managing tasks, schedules, hooks, and execution history. Built with SQLAlchemy, APScheduler, and Typer, it provides a foundation for automated task execution with extensibility through a plugin system.

---

## Features

- **Task Management** — Create, edit, and execute shell commands as managed tasks
- **Scheduling** — Run tasks on cron or interval schedules with APScheduler
- **Execution History** — Track all task runs with stdout/stderr capture and status
- **Hooks** — React to task lifecycle events with shell commands, webhooks, or structured logs
- **Plugin System** — Extend functionality with pluggy-based plugins (builtin: retry, timeout)
- **Configuration** — Multi-source config (env vars, TOML files, defaults) with precedence
- **Data Portability** — Export and import tasks, schedules, and hooks as YAML
- **Rich CLI** — Beautiful terminal output with Rich and full shell completion support
- **FastAPI HTTP API** — RESTful endpoints for all operations with async support
- **Structured Logging** — Production-ready logging with structlog

---

## Installation

Taskmanager uses [uv](https://docs.astral.sh/uv/) for dependency management.

```bash
# Clone the repository
git clone https://github.com/deti/taskmanager
cd taskmanager

# Install dependencies (creates .venv automatically)
uv sync

# Initialize the database
uv run python -c "from taskmanager.database import get_engine, Base; from taskmanager.models import Task, Run, Schedule, Hook; Base.metadata.create_all(get_engine())"

# Install shell completions (optional, recommended)
uv run taskmanager --install-completion
```

---

## Quickstart

Get up and running in 5 commands:

```bash
# 1. Initialize the database
uv run python -c "from taskmanager.database import get_engine, Base; from taskmanager.models import Task, Run, Schedule, Hook; Base.metadata.create_all(get_engine())"

# 2. Create your first task
uv run taskmanager task add --name hello --command "echo 'Hello from taskmanager!'"

# 3. List all tasks
uv run taskmanager task list

# 4. Execute the task
uv run taskmanager task exec hello

# 5. View execution history
uv run taskmanager run list
```

---

## Command Reference

### Shell Completion

Taskmanager provides tab completion for bash, zsh, and fish shells via Typer's built-in support:

```bash
# Install completion for your current shell
taskmanager --install-completion

# Show the completion script (for manual installation or customization)
taskmanager --show-completion
```

After installation, tab-complete commands like `taskmanager task <TAB>` to see available subcommands.

### Core Commands

#### `serve`

Start the FastAPI HTTP server.

```bash
taskmanager serve

# Override host and port
taskmanager serve --host 0.0.0.0 --port 9000
```

Options:
- `--host TEXT` — Host to bind to (overrides settings)
- `--port INTEGER` — Port to bind to (overrides settings)

#### `show-settings`

Display all application settings as JSON. Shows configuration from all sources (environment variables, TOML file, defaults) with precedence order: env > TOML > defaults.

```bash
taskmanager show-settings
```

### Task Management (`task`)

Manage the task registry — create, list, view, edit, remove, and execute tasks.

```bash
# Add a new task
taskmanager task add --name backup-db --command "pg_dump mydb > backup.sql" --description "Daily database backup"

# List all tasks
taskmanager task list

# Show task details
taskmanager task show backup-db

# Edit a task (partial updates supported)
taskmanager task edit backup-db --command "pg_dump mydb | gzip > backup.sql.gz"

# Remove a task
taskmanager task remove backup-db

# Execute a task immediately (creates a Run record)
taskmanager task exec backup-db
```

**Commands:**
- `add` — Create a new task in the registry
  - `--name TEXT` — Unique task name (required)
  - `--command TEXT` — Shell command to execute (required)
  - `--description TEXT` — Optional task description
  - `--shell TEXT` — Shell to use (default: `/bin/sh`)
- `list` — List all tasks in the registry
- `show NAME` — Show detailed information for a specific task
- `edit NAME` — Edit an existing task (partial updates)
  - `--name TEXT` — New name (renames the task)
  - `--command TEXT` — New command
  - `--description TEXT` — New description
  - `--shell TEXT` — New shell
- `remove NAME` — Remove a task from the registry
- `exec NAME` — Execute a task immediately and record the run

### Run History (`run`)

View task execution history with status, timestamps, stdout, stderr, and exit codes.

```bash
# List recent runs (reverse chronological, most recent first)
taskmanager run list

# Filter by status
taskmanager run list --status failed
taskmanager run list --status success

# Filter by task name
taskmanager run list --task backup-db

# Limit results
taskmanager run list --limit 10

# Show run details (supports short ID prefix — first 8 characters)
taskmanager run show a1b2c3d4
taskmanager run show a1b2c3d4-e5f6-7890-abcd-ef1234567890

# View stdout and stderr for a run
taskmanager run logs a1b2c3d4
```

**Commands:**
- `list` — List task runs in reverse chronological order
  - `--status TEXT` — Filter by status: pending, running, success, failed, cancelled
  - `--task TEXT` — Filter by task name
  - `--limit INTEGER` — Limit results (default: 20)
- `show RUN_ID` — Show detailed information for a specific run (accepts short ID)
- `logs RUN_ID` — Display stdout and stderr for a run (accepts short ID)

**Inline execution** — Execute arbitrary commands without creating a task:

```bash
# Execute a command inline (creates a Run record, no Task)
taskmanager run exec "echo 'Quick test'"
```

### Scheduling (`schedule`)

Manage task schedules with cron expressions or intervals. Powered by APScheduler.

```bash
# Add a cron schedule (every day at 2am)
taskmanager schedule add backup-daily --task backup-db --cron "0 2 * * *"

# Add an interval schedule (every 30 minutes)
taskmanager schedule add health-check --task ping-service --interval 30m

# List all schedules
taskmanager schedule list

# Show schedule details
taskmanager schedule show backup-daily

# Enable a schedule
taskmanager schedule enable backup-daily

# Disable a schedule (keeps config, stops execution)
taskmanager schedule disable backup-daily

# Remove a schedule
taskmanager schedule remove backup-daily

# Trigger a schedule immediately (runs once, doesn't affect schedule)
taskmanager schedule trigger backup-daily
```

**Commands:**
- `add NAME` — Create a new schedule
  - `--task TEXT` — Task name to schedule (required)
  - `--cron TEXT` — Cron expression (e.g., `0 2 * * *`)
  - `--interval TEXT` — Interval with unit (e.g., `30m`, `1h`, `5s`) — supports `s`, `m`, `h`, `d`
  - Note: `--cron` and `--interval` are mutually exclusive
- `list` — List all schedules
- `show NAME` — Show detailed information for a specific schedule
- `edit NAME` — Edit an existing schedule
- `enable NAME` — Enable a schedule (starts execution)
- `disable NAME` — Disable a schedule (stops execution, keeps config)
- `remove NAME` — Remove a schedule (deletes config)
- `trigger NAME` — Trigger a schedule immediately (one-time execution)

### Hooks (`hook`)

React to task lifecycle events with shell commands, HTTP webhooks, or structured logs.

```bash
# Add a shell command hook (runs on every task failure)
taskmanager hook add alert-on-failure --event on_after_execute --action shell --shell-command "notify-send 'Task failed'"

# Add a webhook hook (calls HTTP endpoint on success)
taskmanager hook add webhook-success --event on_after_execute --action webhook --webhook-url https://api.example.com/notify

# Add a log hook (structured logging on task start)
taskmanager hook add log-start --event on_before_execute --action log --log-message "Task starting: {task.name}"

# Filter hook to specific task
taskmanager hook add backup-alert --event on_after_execute --action shell --shell-command "echo 'Backup done'" --task backup-db

# List all hooks
taskmanager hook list

# Show hook details
taskmanager hook show alert-on-failure

# Enable/disable hooks
taskmanager hook enable alert-on-failure
taskmanager hook disable alert-on-failure

# Remove a hook
taskmanager hook remove alert-on-failure

# Test a hook (executes the action immediately)
taskmanager hook test alert-on-failure
```

**Commands:**
- `add NAME` — Create a new hook
  - `--event TEXT` — Event to trigger on: `on_before_execute`, `on_after_execute`, `on_schedule_add`, etc.
  - `--action TEXT` — Action type: `shell`, `webhook`, `log`
  - `--task TEXT` — Optional: filter to specific task name (omit for global hooks)
  - **For shell action:**
    - `--shell-command TEXT` — Shell command to execute (required)
  - **For webhook action:**
    - `--webhook-url TEXT` — HTTP endpoint to POST to (required)
    - `--webhook-headers JSON` — Optional HTTP headers as JSON
  - **For log action:**
    - `--log-message TEXT` — Log message template (required, supports `{task.name}`, `{run.id}` placeholders)
    - `--log-level TEXT` — Log level: `debug`, `info`, `warning`, `error` (default: `info`)
- `list` — List all hooks
- `show NAME` — Show detailed information for a specific hook
- `enable NAME` — Enable a hook
- `disable NAME` — Disable a hook (keeps config, stops execution)
- `remove NAME` — Remove a hook
- `test NAME` — Test a hook by executing its action immediately

### Configuration (`config`)

Manage application configuration with multi-source support (env vars, TOML files, defaults).

```bash
# Initialize a config file (creates taskmanager.toml)
taskmanager config init

# Show all configuration with sources
taskmanager config show

# Show config file path
taskmanager config path

# Set a configuration value (writes to TOML file)
taskmanager config set LOG_LEVEL debug
taskmanager config set DATABASE_URL sqlite:///custom.db
```

**Commands:**
- `init` — Create a config file template at `taskmanager.toml`
- `show` — Display all configuration with source hierarchy (env > file > defaults)
- `path` — Show the path to the config file
- `set KEY VALUE` — Set a configuration value in the TOML file

**Configuration precedence:** Environment variables > TOML file > defaults

### Plugins (`plugin`)

Manage the plugin system — list loaded plugins and view their status.

```bash
# List all plugins
taskmanager plugin list

# Show plugin details (hooks implemented, load status, errors)
taskmanager plugin info retry
```

**Commands:**
- `list` — List all loaded plugins with status
- `info NAME` — Show detailed information about a plugin (hooks, status, errors)

**Builtin plugins:**
- `retry` — Automatically retry failed tasks with exponential backoff (configure with `retry_count` in task metadata)
- `timeout` — Kill tasks that exceed a timeout (configure with `timeout_seconds` in task metadata)

### History Management (`history`)

Manage run history retention and view statistics.

```bash
# Prune old run records (default: keep last 90 days)
taskmanager history prune

# Prune with custom retention (keep last 30 days)
taskmanager history prune --days 30

# View execution statistics
taskmanager history stats
```

**Commands:**
- `prune` — Delete old run records
  - `--days INTEGER` — Retention period in days (default: 90)
- `stats` — Display execution statistics (total runs, success rate, task breakdown)

### Data Import/Export (`data`)

Export and import tasks, schedules, and hooks as YAML for portability and backup.

```bash
# Export all data to YAML
taskmanager data export --output backup.yaml

# Import data from YAML
taskmanager data import --input backup.yaml

# Import with conflict resolution
taskmanager data import --input backup.yaml --on-conflict skip
taskmanager data import --input backup.yaml --on-conflict overwrite
```

**Commands:**
- `export` — Export tasks, schedules, and hooks to YAML
  - `--output PATH` — Output file path (default: `taskmanager-export.yaml`)
- `import` — Import tasks, schedules, and hooks from YAML
  - `--input PATH` — Input file path (required)
  - `--on-conflict TEXT` — Conflict resolution: `skip` (keep existing), `overwrite` (replace), `fail` (abort on conflict)

**YAML format:** Human-readable structure with separate sections for tasks, schedules, and hooks. See exported files for reference.

---

## Configuration Reference

Taskmanager supports multiple configuration sources with precedence: **environment variables > TOML file > defaults**.

### Environment Variables

All configuration can be set via environment variables:

```bash
# Application settings
export APP_NAME="taskmanager"
export DEBUG="false"
export LOG_LEVEL="info"           # debug, info, warning, error
export ENVIRONMENT="production"   # development, test, production

# Server settings
export HOST="127.0.0.1"
export PORT="8000"

# Database
export DATABASE_URL="sqlite:///taskmanager.db"
```

### TOML Configuration File

Create a `taskmanager.toml` file in the working directory:

```toml
APP_NAME = "taskmanager"
DEBUG = false
LOG_LEVEL = "info"
ENVIRONMENT = "production"
HOST = "127.0.0.1"
PORT = 8000
DATABASE_URL = "sqlite:///taskmanager.db"
```

Generate a template:

```bash
taskmanager config init
```

### Configuration Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `APP_NAME` | string | `"taskmanager"` | Application name for logging |
| `DEBUG` | boolean | `false` | Enable debug mode |
| `LOG_LEVEL` | string | `"info"` | Logging level: debug, info, warning, error |
| `ENVIRONMENT` | string | `"development"` | Environment: development, test, production |
| `HOST` | string | `"127.0.0.1"` | HTTP server bind host |
| `PORT` | integer | `8000` | HTTP server bind port |
| `DATABASE_URL` | string | `"sqlite:///taskmanager.db"` | SQLAlchemy database URL |

### Viewing Configuration

```bash
# Show all settings with sources
taskmanager show-settings

# Show config file path
taskmanager config path

# Show settings with source hierarchy
taskmanager config show
```

---

## Plugin Development Guide

Taskmanager uses [pluggy](https://pluggy.readthedocs.io/) for its plugin system. Plugins can hook into task lifecycle events to extend functionality.

### Plugin Architecture

1. **Hookspecs** — Defined in `src/taskmanager/hookspecs.py`, these declare the available plugin hooks
2. **Hook Implementations** — Plugins implement hooks using the `@hookimpl` decorator
3. **Plugin Manager** — Discovers and loads plugins from entry points
4. **Builtin Plugins** — Retry and timeout plugins serve as reference implementations

### Available Hooks

| Hook | Parameters | Description |
|------|------------|-------------|
| `on_before_execute` | `task: Task, run: Run` | Called before task execution starts |
| `on_after_execute` | `task: Task, run: Run` | Called after task execution completes |
| `on_task_create` | `task: Task` | Called when a new task is created |
| `on_task_delete` | `task: Task` | Called when a task is deleted |
| `on_schedule_add` | `schedule: Schedule` | Called when a schedule is added |
| `on_schedule_remove` | `schedule: Schedule` | Called when a schedule is removed |
| `register_commands` | `app: typer.Typer` | Register custom CLI commands |
| `register_api_routes` | `router: APIRouter` | Register custom HTTP API routes |

### Creating a Plugin

#### 1. Create the plugin module

```python
# my_plugin.py
from pluggy import HookimplMarker
from taskmanager.models import Task, Run
from taskmanager.logging import get_logger

logger = get_logger(__name__)
hookimpl = HookimplMarker("taskmanager")

class MyPlugin:
    """Example plugin that logs task execution."""

    @hookimpl
    def on_before_execute(self, task: Task, run: Run) -> None:
        """Log when a task starts."""
        logger.info("task_starting", task_name=task.name, run_id=run.id)

    @hookimpl
    def on_after_execute(self, task: Task, run: Run) -> None:
        """Log when a task completes."""
        logger.info(
            "task_completed",
            task_name=task.name,
            run_id=run.id,
            status=run.status,
            exit_code=run.exit_code,
        )

# Plugin instance (must be named with _plugin suffix for discovery)
my_plugin = MyPlugin()
```

#### 2. Register the plugin entry point

Add to `pyproject.toml`:

```toml
[project.entry-points."taskmanager.plugins"]
my_plugin = "my_plugin:my_plugin"
```

#### 3. Install and verify

```bash
# Install in development mode
uv pip install -e .

# Verify plugin is loaded
taskmanager plugin list
taskmanager plugin info my_plugin
```

### Builtin Plugin Examples

#### Retry Plugin

Automatically retries failed tasks with exponential backoff:

```python
# Configure in task metadata
task = create_task(
    session=session,
    name="flaky-task",
    command="curl https://api.example.com",
    task_metadata={"retry_count": 3}  # Retry up to 3 times
)
```

Retry delays: 1s (2^0), 2s (2^1), 4s (2^2)

See: `src/taskmanager/plugins/builtin/retry.py`

#### Timeout Plugin

Kills tasks that exceed a timeout:

```python
# Configure in task metadata
task = create_task(
    session=session,
    name="long-task",
    command="sleep 60",
    task_metadata={"timeout_seconds": 30}  # Kill after 30 seconds
)
```

See: `src/taskmanager/plugins/builtin/timeout.py`

### Plugin Best Practices

- **Error handling** — Plugins should never crash the main application; use try/except
- **Logging** — Use `taskmanager.logging.get_logger()` for structured logs
- **Database access** — Hooks receive SQLAlchemy models; get session from `inspect(model).session`
- **Performance** — Keep hook implementations fast; offload heavy work to background tasks
- **Testing** — Test plugins with mocked hookspec calls before installing

---

## Architecture

Taskmanager follows a layered architecture under `src/taskmanager/`:

```
src/taskmanager/
├── main.py              # FastAPI app instance and lifespan
├── settings.py          # Pydantic Settings with multi-source config
├── cli/                 # Typer CLI commands
│   ├── __init__.py      # Main CLI app entry point
│   ├── task.py          # Task CRUD commands
│   ├── run.py           # Run history commands
│   ├── schedule.py      # Schedule management
│   ├── hook.py          # Hook management
│   ├── plugin.py        # Plugin management
│   ├── config.py        # Config commands
│   ├── history.py       # History pruning and stats
│   └── data.py          # Import/export
├── models/              # SQLAlchemy ORM models
│   ├── task.py          # Task model
│   ├── run.py           # Run model
│   └── schedule.py      # Schedule model
├── services/            # Business logic
│   ├── task_service.py  # Task CRUD operations
│   └── run_service.py   # Run queries and history
├── api/                 # FastAPI routes
├── executor.py          # Task execution engine
├── database.py          # SQLAlchemy engine and session factory
├── plugins/             # Plugin system
│   ├── __init__.py      # PluginManager
│   ├── hookspecs.py     # Hook specifications
│   └── builtin/         # Builtin plugins (retry, timeout)
├── logging.py           # Structlog configuration
└── exceptions.py        # Domain exceptions
```

**Entry points** (defined in `pyproject.toml`):
- `taskmanager` → `taskmanager.cli:main`
- `serve` → `taskmanager.cli.serve:serve`
- `show-settings` → `taskmanager.cli.show_settings:show_settings`

---

## Development

### Setup

```bash
# Clone and install with dev dependencies
git clone https://github.com/deti/taskmanager
cd taskmanager
uv sync

# Initialize database
uv run python -c "from taskmanager.database import get_engine, Base; from taskmanager.models import Task, Run; Base.metadata.create_all(get_engine())"
```

### Development Commands

```bash
# Linting and formatting
make lint          # Run ruff linter
make format        # Run ruff formatter

# Type checking
make typecheck     # Run mypy in strict mode

# Testing
make test          # Run pytest
make test-cov      # Run pytest with coverage report

# Run specific test
uv run pytest tests/test_main.py::test_app_instance -v

# Combined checks
make check         # Run lint + typecheck + tests in sequence

# Development server
make serve         # Start API server with hot reload
```

### Makefile Targets

| Target | Description |
|--------|-------------|
| `make init` | Create venv and install all dependencies |
| `make sync` | Install dev dependencies (faster, no venv creation) |
| `make check` | Run lint + typecheck + tests in sequence |
| `make lint` | Ruff linter |
| `make format` | Ruff formatter |
| `make typecheck` | Mypy strict type checking |
| `make test` | pytest tests/ -v |
| `make test-cov` | pytest with HTML + terminal coverage report |
| `make serve` | Start API server (uvicorn on 127.0.0.1:8000) |
| `make show-settings` | Print current settings as JSON |

### Testing

Taskmanager uses pytest with async support and in-memory SQLite for tests:

```bash
# Run all tests
make test

# Run with coverage
make test-cov

# Run specific test file
uv run pytest tests/cli/test_task.py -v

# Run specific test
uv run pytest tests/cli/test_task.py::test_add_task -v
```

Test environment isolation: Set `ENVIRONMENT=test` in test fixtures to use test-specific settings.

---

## License

MIT License — see LICENSE file for details.

---

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Run `make check` to ensure lint, typecheck, and tests pass
4. Commit your changes (`git commit -m 'Add amazing feature'`)
5. Push to the branch (`git push origin feature/amazing-feature`)
6. Open a Pull Request

---

## Support

- **Issues:** [GitHub Issues](https://github.com/deti/taskmanager/issues)
- **Documentation:** This README
- **Source:** [GitHub Repository](https://github.com/deti/taskmanager)
