# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
make init          # Create venv and install all dependencies
make sync          # Install dev dependencies (faster, no venv creation)

# Development cycle
make check         # Run lint + typecheck + tests in sequence
make lint          # Ruff linter
make format        # Ruff formatter
make typecheck     # Mypy strict type checking
make test          # pytest tests/ -v
make test-cov      # pytest with HTML + terminal coverage report

# Run a single test
uv run pytest tests/test_main.py::test_app_instance -v

# Application
make serve         # Start API server (uvicorn on 127.0.0.1:8000)
make show-settings # Print current settings as JSON
```

## Architecture

**Stack:** FastAPI + Typer CLI + Pydantic Settings + SQLAlchemy + uv

The app follows a layered architecture under `src/taskmanager/`:

- **`main.py`** — FastAPI app instance and route definitions
- **`settings.py`** — `Settings` (Pydantic BaseSettings) loaded from env vars / `.env`; accessed via cached `get_settings()`. No env prefix — variables are `APP_NAME`, `DEBUG`, `LOG_LEVEL`, `ENVIRONMENT`, `HOST`, `PORT`.
- **`cli/`** — Typer app with two commands: `serve` (starts uvicorn) and `show-settings` (prints settings JSON)
- **`models/`** — SQLAlchemy ORM models (empty, ready for use)
- **`services/`** — Business logic layer (empty, ready for use)

**Entry points** (defined in `pyproject.toml` `[project.scripts]`):
- `taskmanager` → `taskmanager.cli:app`
- `serve` → `taskmanager.cli.serve:serve`
- `show-settings` → `taskmanager.cli.show_settings:show_settings`

**Dependencies installed but not yet wired up:** SQLAlchemy (ORM), APScheduler (job scheduling), structlog (structured logging), pluggy (plugin system), Rich (terminal output).

**Testing:** pytest-asyncio for async FastAPI tests; `ENVIRONMENT=test` should be set in test fixtures to isolate settings. No database fixtures exist yet — when SQLAlchemy is wired up, add session fixtures in `tests/conftest.py`.

**Tooling:** `uv` manages the virtualenv and dependencies (replaces pip/venv). `ruff` handles both linting and formatting. `mypy` runs in strict mode — all new code needs type annotations.

## Fleet

This repo uses Fleet for multi-agent orchestration (`.fleet/`). Six crews own different layers:
- **core-domain** — Task model, domain exceptions
- **persistence** — SQLAlchemy engine, sessions, migrations
- **task-service** — TaskService CRUD and business logic
- **api** — FastAPI routes and Pydantic schemas
- **cli** — Typer commands
- **config** — Settings and env vars

`merge_strategy: local` — crews commit locally; no PRs created. `ralph_enabled: true` — Ralph auto-continuation is active.

## Git Constraints

**Do not merge, rebase, or fast-forward any other branch into any branch except the currently checked-out branch.** All work must stay on the current working branch, and all final changes must end up there. Do not switch the final target to another branch, do not create integration merges elsewhere, and do not ask to merge into main, master, develop, or any other branch. If code from another branch is needed, only bring it into the current checked-out branch.

## Pre-Commit Checklist

```bash
make lint
make test
```