# AGENTS.md

Guidelines for AI coding agents working in this repository.

## Project Overview

Python application for analyzing diabetes management during running activities.
Integrates Strava (running data) and CareLink (CGM/insulin data) with a FastAPI web app (Jinja2 + Plotly).

- **Python:** >=3.12, <3.13
- **Package manager:** uv (lockfile: `uv.lock`)
- **Build system:** Hatchling
- **Architecture:** `data_fetcher` (API clients) -> `data_models` (schemas/enums/paths) -> `data_processing` (business logic) -> `dashboard` (Plotly chart functions) + `web` (FastAPI + Jinja2)

## Build & Run Commands

```bash
# Install dependencies
uv sync

# Set up pre-commit hooks (ruff + mypy)
uv run pre-commit install

# Run pre-commit hooks manually on all files
uv run pre-commit run --all-files

# Run the data fetcher CLI
uv run fetch

# Run the FastAPI web app
uv run uvicorn dia_run.web.app:app --reload

# Run via Docker Compose
docker compose up --build

# Linting
uv run ruff check src/ tests/
uv run ruff check --fix src/ tests/

# Formatting
uv run ruff format src/ tests/
uv run ruff format --check src/ tests/

# Type checking
uv run mypy src/

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_data_processing/test_data_processor.py

# Run a single test by name
uv run pytest -k "test_get_summary"

# Run tests with coverage
uv run pytest --cov=dia_run

# Version bump (commitizen)
uv run cz bump
```

## Code Style

### Formatting & Linting (Ruff)

- **Line length:** 120 characters
- **Enabled rules:** E (pycodestyle), F (pyflakes), D (pydocstyle), B (bugbear), I (isort), ARG (unused args), PLR0917 (max positional args)
- **Ignored D rules:** D100-D107 (missing docstrings for modules/classes/functions), D203, D213, D417
- Ruff handles both linting and formatting. Always run `ruff check` and `ruff format` before committing.

### Imports

- Order: standard library, third-party, local (enforced by isort via ruff `I` rule)
- Use absolute imports from the package root: `from dia_run.data_models.paths import DataPaths`
- No wildcard imports

### Type Annotations (mypy strict mode)

- **All functions must have complete type annotations** (enforced by `disallow_untyped_defs`, `disallow_untyped_calls`, `disallow_incomplete_defs`)
- Use modern union syntax: `X | None` (not `Optional[X]`)
- Use `pl.DataFrame | None` for nullable DataFrames
- Use Pandera `DataFrame[Schema]` for validated return types
- Use `TypeVar` for generic methods

### Naming Conventions

| Element          | Convention         | Example                          |
|------------------|--------------------|----------------------------------|
| Classes          | PascalCase         | `DataProcessor`, `RunType`       |
| Functions/methods| snake_case         | `get_summary`, `create_chart`    |
| Private methods  | `_leading_underscore` | `_load_summary_data`          |
| Constants        | UPPER_SNAKE_CASE   | `PRE_RUN_INSULIN_MINUTES = 180`  |
| Enums            | StrEnum, UPPER members | `RunType.EASY`, `RunType.INTERVAL` |
| Files            | snake_case         | `data_processing.py`             |

### Keyword-Only Arguments

- **Max 1 positional argument** enforced by ruff PLR0917
- Use `*` separator for keyword-only args: `def __init__(self, *, data_paths: DataPaths)`
- This applies to all functions and methods (except `self`/`cls`)

### Error Handling

- Raise `ValueError` with descriptive messages for business logic errors
- Use early-return patterns with `None` checks
- Log with `loguru`: `from loguru import logger`, then `logger.info(...)`, `logger.error(...)`
- Avoid broad `except` clauses in application code

### Data Processing Patterns

- **Polars** is the primary DataFrame library (not pandas). Use lazy frames (`pl.scan_delta()`) and materialize with `.collect()`
- **Delta Lake** for data storage: read with `pl.scan_delta()`, write with `df.write_delta()`
- **Pandera** `@check_types` decorator on public data-returning methods for runtime schema validation
- **Pydantic** `BaseModel` for configuration and structured data models
- Prefer method chaining: `.with_columns()`, `.filter()`, `.select()`, `.join()`

## Testing

- **Framework:** pytest with `pytest-cov`
- **Test paths:** `tests/` and `src/` (configured in pyproject.toml)
- Tests use session-scoped fixtures in `tests/conftest.py` that create Delta Lake tables in temp directories
- Test classes: `TestClassName` with methods `test_method_name`
- Use standard `assert` statements
- Validate schemas explicitly in tests: `SummarySchema.validate(result)`
- Fixtures must use keyword-only arguments (matching the project-wide convention)

### Writing Tests

```python
import polars as pl
import pytest

from dia_run.data_models.paths import DataPaths
from dia_run.data_processing.data_processing import DataProcessor


class TestNewFeature:
    def test_does_something(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(data_paths=test_data_paths)
        result = processor.some_method()
        assert result is not None
```

## Commit Convention

- **Conventional Commits** enforced via commitizen: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`
- Semver versioning with tag format `v$version`
- CI validates PRs into `main`, and tags `main` on release promotion from `release/*` or `hotfix/*`
- Commit message in bump: `release $current_version -> $new_version [commitizen-skip-ci]`

## Branching And Release Strategy

- Cut all feature branches from `develop`
- Open feature PRs into `develop`; treat `main` as production
- Do not push directly to `develop` or `main`
- Only open PRs into `main` from `release/*` or `hotfix/*`
- PRs into `main` must include a version bump, `uv.lock`, and `CHANGELOG.md`
- After a hotfix or release lands on `main`, back-merge it into `develop`

### Release Workflow

- Create `release/<planned-version>` from `develop` when `develop` is ready to ship
- Prepare release metadata on the release branch with `uvx --from commitizen cz bump --yes --changelog --version-files-only`
- Commit the release prep changes, open a PR from `release/*` to `main`, then merge the same release branch back into `develop`

### Hotfix Workflow

- Create `hotfix/*` branches from `main`
- Prepare release metadata on the hotfix branch before opening the PR into `main`
- After the hotfix is merged to `main`, back-merge it into `develop`

## Project Structure

```
src/dia_run/
  data_fetcher/          # API clients (Strava, CareLink) and CLI
    carelink_client.py   # Vendored CareLink API client
    strava_client.py     # Strava API wrapper
    data_fetcher.py      # CLI entry point (fetch command)
    questionnaire.py     # Interactive run questionnaire
  data_models/           # Schemas, enums, path config
    schemas.py           # Pandera DataFrameSchemas
    run_types.py         # RunType StrEnum
    paths.py             # DataPaths Pydantic model
    questionnaire.py     # QuestionnaireModel Pydantic model
    calendar.py          # Calendar model
  data_processing/       # Business logic
    data_processing.py   # DataProcessor class (central data pipeline)
  dashboard/             # Plotly chart functions (pure functions)
    charts/              # Plotly chart functions (pure functions)
  web/                   # FastAPI web app (Jinja2 templates)
    app.py               # FastAPI app entry point
    routes/              # FastAPI routes
    templates/           # Jinja2 templates
    static/              # CSS and static assets
tests/
  conftest.py            # Session-scoped fixtures with Delta Lake test data
  test_data_processing/  # Tests for data processing logic
```

## Key Files

- `pyproject.toml` — All project config (deps, ruff, mypy, pytest, commitizen)
- `src/dia_run/data_processing/data_processing.py` — Core business logic
- `src/dia_run/data_models/schemas.py` — All Pandera schemas
- `tests/conftest.py` — Test data setup (Delta Lake tables in tmpdir)

## Architecture Diagram

A Mermaid class diagram is maintained at **`docs/diagram.mmd`**. It is a living document that must stay in sync with the codebase.

### What the diagram covers

- All classes, Pydantic models, Pandera `DataFrameModel` schemas, Protocols, and StrEnums defined under `src/dia_run/`
- Key properties/fields and public methods for each class
- Function-only modules (e.g. chart modules, web routes) represented as `<<module>>` stereotyped classes listing their public functions
- Relationships: inheritance (`--|>`), composition (`*--`), protocol implementation (`..|>`), and dependency (`..>` / `-->`)

### When to update `docs/diagram.mmd`

You **must** update the diagram whenever any of the following structural changes are made to files under `src/dia_run/`:

1. A **class, schema, enum, or protocol** is added, removed, or renamed
2. A **public method or property** is added, removed, or has its signature changed on any class
3. A **field/attribute** is added or removed from a Pydantic model, DataFrameModel schema, or dataclass
4. A **relationship** between classes changes (new dependency, changed inheritance, new composition)
5. A **new module** is created or an existing module is deleted
6. A **function-only module** gains or loses a public function

### How to update

1. Open `docs/diagram.mmd` and apply the structural change (add/remove/rename the class, method, field, or relationship)
2. Ensure the Mermaid syntax is valid — the file should be renderable with: `mmdc -i docs/diagram.mmd -o docs/diagram.svg`
3. Commit the updated `docs/diagram.mmd` alongside the code change that triggered the update
