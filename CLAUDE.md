# CLAUDE.md

Read `AGENTS.md` for the full project overview, build commands, code style, testing, commit conventions, branching strategy, and project structure. That file is the source of truth — do not duplicate its content here.

## Quick Reference

```bash
# Install deps
uv sync

# Lint + format + type check
uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/

# Auto-fix lint/format
uv run ruff check --fix src/ tests/ && uv run ruff format src/ tests/

# Run tests
uv run pytest

# Run app (mock mode: set USE_MOCK_DATA=true in .env)
uv run uvicorn dia_run.web.app:app --reload

# Pre-commit hooks
uv run pre-commit run --all-files
```

## Critical Rules

- **Max 1 positional argument** — use `*` separator for keyword-only args (enforced by ruff PLR0917)
- **Strict mypy** — every function needs full type annotations, use `X | None` not `Optional[X]`
- **Polars, not pandas** — use lazy frames (`pl.scan_delta()`) and materialize with `.collect()`
- **Conventional commits** — `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`
- **Never push directly** to `develop` or `main` — always use PRs
- **Update `docs/diagram.mmd`** when structural changes are made (classes, methods, schemas)
