Run all code quality checks and auto-fix what's possible.

Steps:
1. Run `uv run ruff check src/ tests/` — report any errors
2. Run `uv run ruff format --check src/ tests/` — report formatting issues
3. Run `uv run mypy src/` — report type errors
4. If there are auto-fixable issues, run:
   - `uv run ruff check --fix src/ tests/`
   - `uv run ruff format src/ tests/`
5. Re-run checks to confirm everything is clean
6. Report any remaining issues that need manual fixes
