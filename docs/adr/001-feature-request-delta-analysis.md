# ADR-001: Feature Request Delta Analysis — Conflict Resolution

| Field        | Value                                              |
|--------------|----------------------------------------------------|
| **Status**   | Proposed                                           |
| **Date**     | 2026-03-30                                         |
| **Authors**  | Architect (Claude)                                 |
| **Scope**    | `pyproject.toml`, CLI subsystem, linter config     |

## Context

A feature request targets the `taskmanager` project (v0.1.0, generated from cookiecutter) with changes that conflict with the existing project configuration on five axes.  The project is at an early stage — one commit on `master`, minimal feature surface (single GET `/` endpoint, two CLI entrypoints, pydantic-settings-based configuration).  Because the project is pre-release, this is the ideal moment to resolve configuration drift; the cost of breaking changes is near-zero.

The current state is summarised below for reference:

| Aspect              | Current value                                                     |
|---------------------|-------------------------------------------------------------------|
| `requires-python`   | `>=3.14`                                                          |
| Runtime deps        | `pydantic-settings`, `fastapi`, `uvicorn`, `click` (all unpinned)|
| Dev deps            | `anyio`, `httpx`, `pytest`, `pytest-asyncio`, `ruff` (all unpinned) |
| CLI framework       | `click`; entrypoints `show-settings`, `serve`                     |
| Ruff line-length    | 88                                                                |
| Ruff rule set       | Broad (30 rule groups)                                            |
| Ruff ignored rules  | `PLR0913`, `PLR2004`, `N999`                                      |

---

## Decision 1 — `requires-python` version constraint

### Conflict

The existing `pyproject.toml` declares `requires-python = ">=3.14"`.  The feature request targets **Python 3.12+**.

### Decision

**Change to `requires-python = ">=3.12"`.**

### Rationale

1. **Python 3.14 is in alpha** (as of March 2026).  Requiring it excludes all users on stable Python releases (3.12, 3.13), which is incompatible with any near-term adoption or CI/CD pipeline that runs on stable interpreters.
2. The codebase uses no Python-3.14-only features.  The only modern syntax present is `str | None` union types (PEP 604), which landed in **Python 3.10**.
3. The project's key dependencies (`fastapi`, `pydantic-settings`, `uvicorn`) all support Python 3.12+.
4. Widening to `>=3.12` aligns with the standard support window: 3.12 reaches end-of-life in October 2028, giving over two years of runway.
5. If the feature request's goal is to support a broader user base (implied by "playground" positioning), excluding stable Python is counter-productive.

### Constraint to apply

```toml
requires-python = ">=3.12"
```

### Risk

None material.  The existing `.venv` was created with Python 3.14; the developer will need to recreate it if they intend to test on 3.12/3.13, but this is a standard workflow.

---

## Decision 2 — CLI framework: Click vs. Typer migration

### Conflict

The existing CLI is built on **Click** with two registered entrypoints (`show-settings` → `taskmanager.cli.show_settings:main`, `serve` → `taskmanager.cli.serve:main`).  The feature request introduces `typer[all]` and implies a unified `taskmanager` entrypoint (`uv run taskmanager --help`).

### Decision

**Migrate from Click to Typer now, and register a single `taskmanager` entrypoint.  Remove the `click` dependency.**

### Rationale

1. **Typer wraps Click** — it is not a competing framework but a higher-level API on top of Click.  Migration cost is minimal because Typer uses the same underlying runtime.
2. The existing Click surface is very small: one `@click.command()` with two `@click.option()` decorators in `serve.py`, and `show_settings.py` uses no Click at all.  Total migration: ~10 lines.
3. A single `taskmanager` entrypoint with subcommands (`taskmanager serve`, `taskmanager show-settings`) is superior to two separate script entrypoints because:
   - **Discoverability**: `taskmanager --help` shows all available commands.
   - **Consistency**: one namespace, one invocation pattern.
   - **Extensibility**: adding future commands (e.g. `taskmanager migrate`, `taskmanager worker`) is trivial — just add a function with a `@app.command()` decorator.
4. Typer provides automatic `--help` generation, shell completion, and rich output (via `typer[all]`), all of which support the "playground" positioning.
5. The project has only one commit and zero external consumers.  There is no backward-compatibility cost.

### Entrypoint strategy

```toml
[project.scripts]
taskmanager = "taskmanager.cli:app"
```

Where `taskmanager/cli/__init__.py` creates the Typer app and imports subcommands:

```
taskmanager/cli/
├── __init__.py      # typer.Typer() app, registers subcommands
├── serve.py         # @app.command() — start uvicorn
└── show_settings.py # @app.command() — dump settings JSON
```

The existing `show-settings` and `serve` bare entrypoints are **removed**.  The Makefile targets `show-settings` and `serve` are updated to call `uv run taskmanager show-settings` and `uv run taskmanager serve` respectively.

### Acceptance criterion satisfied

`uv run taskmanager --help` will output the Typer-generated help text listing `serve` and `show-settings` as subcommands.

### Risk

- Tests in `tests/cli/test_serve.py` reference `main.callback(...)`, which is a Click-specific API.  These tests must be rewritten to invoke the Typer test runner (`typer.testing.CliRunner`) or call the underlying functions directly.  The test rewrite is small (~10 test functions) and improves test fidelity.
- The `click` dependency is removed.  If any transitive dependency brings Click in (Typer does, as it depends on Click), there is no conflict.

---

## Decision 3 — Ruff configuration: replace vs. merge

### Conflict

| Setting         | Current                                      | Feature request               |
|-----------------|----------------------------------------------|-------------------------------|
| `line-length`   | 88                                           | 99                            |
| Rule set        | 30 groups (broad: E4,E7,E9,F,W,B,I,N,UP,...) | Different/smaller set         |
| Ignore list     | PLR0913, PLR2004, N999                       | Different                     |

### Decision

**Replace line-length with 99.  Retain the existing broad rule set (superset merge).  Update ignores as needed.**

### Rationale

1. **Line-length 99 over 88:**
   - 88 is the Black/ruff default, inherited from the cookiecutter template, not a deliberate project choice.
   - 99 is a pragmatic middle ground between 88 (too narrow for descriptive naming and type hints) and 120 (too wide for side-by-side diffs).  It is widely adopted (Django uses 119, Pallets uses 100).
   - At v0.1.0, zero code needs reflowing — the change is free.

2. **Keep the broad rule set (superset strategy):**
   - The current rule set is a well-curated superset that catches real bugs (B), enforces modern Python (UP), organises imports (I), and flags common anti-patterns (SIM, RET, TRY).
   - Removing rules at this stage would reduce code quality safety nets before any code of substance has been written.
   - If the feature request's rule set is smaller, it was likely a minimal starting point, not an intentional exclusion.  The safer merge strategy is to keep the broader set.
   - Rules can always be selectively ignored via `per-file-ignores` or inline `noqa` where needed.

3. **Ignore list — merge both:**
   - Retain `PLR0913` (too many arguments) — valid for CLI/settings constructors.
   - Retain `PLR2004` (magic values) — too noisy for a settings-heavy project.
   - Retain `N999` (invalid module name) — project name hyphen in repo.
   - Add any additional ignores from the feature request that have clear justification.

### Final ruff config to apply

```toml
[tool.ruff]
src = ["src", "tests"]
line-length = 99
indent-width = 4
# (exclude list unchanged)

[tool.ruff.lint]
select = [
    "E4", "E7", "E9", "F", "W", "B", "I", "N", "UP", "C4",
    "ICN", "PIE", "T20", "PYI", "PT", "Q", "RSE", "RET",
    "SLF", "SIM", "TID", "TCH", "ARG", "PTH", "ERA",
    "PGH", "PL", "TRY", "NPY", "RUF",
]
ignore = [
    "PLR0913",  # Too many arguments
    "PLR2004",  # Magic value used in comparison
    "N999",     # Invalid module name (repo hyphen)
]
fixable = ["ALL"]
unfixable = []
```

All other ruff sub-configurations (`format`, `isort`, `per-file-ignores`, `pytest.ini_options`) remain unchanged.

---

## Decision 4 — Dev dependencies: retain or remove `anyio` and `pytest-asyncio`

### Conflict

The existing dev deps include `anyio` and `pytest-asyncio`.  These are not listed in the feature request's dependency set.

### Decision

**Retain both `anyio` and `pytest-asyncio`.  They are actively used and required for the existing test suite.**

### Rationale

1. **`pytest-asyncio`** is directly used: `test_main.py` uses `@pytest.mark.asyncio` on four test functions that exercise the FastAPI ASGI app via `httpx.AsyncClient`.  Removing it would break the test suite.

2. **`anyio`** is a transitive dependency of `httpx` (used in tests for `ASGITransport`) and is required at test time.  While it could theoretically be omitted as a direct dependency (relying on transitive resolution), explicit declaration is the correct practice because:
   - It documents the test suite's async runtime requirement.
   - It protects against `httpx` changing its dependency tree in a future version.
   - PEP 735 (dependency groups) encourages declaring direct usage.

3. The feature request's omission of these packages is likely an oversight — the feature request specifies additions, not a complete replacement of the dev dependency list.

4. Removing async test infrastructure would require rewriting all async tests to use synchronous `TestClient`, which is unnecessary churn that provides no architectural benefit.

### Dev dependency list (merged)

```toml
[dependency-groups]
dev = [
    "anyio",
    "httpx",
    "pytest",
    "pytest-asyncio",
    "ruff",
    # + any new dev deps from the feature request (e.g. pytest-cov)
]
```

---

## Decision 5 — Dependency version pinning

### Conflict

No version constraints exist on any current dependency (runtime or dev).  The feature request specifies pinned versions.

### Decision

**Pin all dependencies to minimum-compatible versions using `>=x.y.z` constraints.  Use the lockfile (`uv.lock`) for reproducible builds.**

### Rationale

1. **Why pin:**
   - Unpinned dependencies are a reliability and security risk.  A breaking release of any dependency can silently break the project for new installs.
   - Pinning communicates tested-against versions to contributors and CI.
   - It is a Twelve-Factor App best practice (factor II: Dependencies).

2. **Why `>=x.y.z` (minimum bounds) rather than `==x.y.z` (exact pins):**
   - `pyproject.toml` is the *abstract* dependency specification for a library/application.  Exact pins belong in the lockfile (`uv.lock`), which already exists.
   - Minimum bounds allow `uv sync` to resolve the latest compatible versions while guaranteeing a known-good floor.
   - Exact pins in `pyproject.toml` create resolution conflicts when the project is used as a dependency itself (or in a monorepo).

3. **Why not leave unpinned:**
   - The project already has a `uv.lock` for reproducibility.  Adding minimum bounds in `pyproject.toml` adds a complementary layer of safety: the lockfile handles "exact reproducibility" and the bounds handle "don't install something ancient that was never tested."

### Pinning strategy

Pin runtime dependencies to the major version currently resolved in `uv.lock`.  Pin dev dependencies to the major version.  Example:

```toml
dependencies = [
    "pydantic-settings>=2.0",
    "fastapi>=0.115",
    "uvicorn>=0.34",
    "typer[all]>=0.15",
]

[dependency-groups]
dev = [
    "anyio>=4.0",
    "httpx>=0.28",
    "pytest>=8.0",
    "pytest-asyncio>=0.25",
    "ruff>=0.11",
]
```

> **Note:** The exact version floors should be confirmed against the currently resolved versions in `uv.lock` at implementation time.  The pattern above is illustrative.

---

## Summary of Decisions

| # | Conflict                            | Decision                                         | Breaking? |
|---|-------------------------------------|--------------------------------------------------|-----------|
| 1 | `requires-python >=3.14` vs `>=3.12`| **Use `>=3.12`**                                 | No        |
| 2 | Click + 2 entrypoints vs Typer + 1  | **Migrate to Typer, single `taskmanager` entrypoint** | Yes (tests) |
| 3 | Ruff line-length 88 vs 99           | **Use 99; keep broad rule set (superset merge)** | No        |
| 4 | Dev deps `anyio`/`pytest-asyncio`   | **Retain both — actively used in test suite**    | No        |
| 5 | No version pins                     | **Add `>=x.y.z` minimum bounds; rely on `uv.lock` for exact pins** | No |

## Consequences

### Positive
- The project supports all stable Python 3.12+ environments, enabling broader adoption and standard CI matrices.
- A single `taskmanager` CLI entrypoint improves UX and simplifies future command additions.
- The broad ruff rule set catches defects early while the wider line-length reduces unnecessary wrapping.
- Minimum version bounds provide dependency safety without lockfile conflicts.

### Negative
- The Typer migration requires rewriting ~10 CLI test functions (Click's `.callback()` API → Typer's `CliRunner` or direct invocation).  Estimated effort: 1–2 hours.
- Developers must recreate their `.venv` if switching from Python 3.14 to 3.12/3.13 for testing.

### Neutral
- The `click` package remains available transitively (Typer depends on it), so no import will break at runtime — only the direct `click` decorators in `serve.py` need replacement.

---

## Architectural Invariants Established

These decisions establish the following invariants for the project going forward:

1. **Single CLI namespace:** All CLI commands are subcommands of `taskmanager`.  No new top-level `[project.scripts]` entrypoints.
2. **Minimum Python 3.12:** No syntax or stdlib features exclusive to 3.13+ without an explicit ADR.
3. **Broad linting by default:** New ruff rules are added, not removed.  Rule removal requires an ignore entry with a comment explaining why.
4. **Explicit dependencies:** Every direct import in `src/` or `tests/` has a corresponding entry in `dependencies` or `[dependency-groups] dev` with a minimum version bound.
