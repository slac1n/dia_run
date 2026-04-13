Guide through the release workflow for this project.

Prerequisites: must be on `develop` with a clean working tree.

Steps:
1. Verify we're on `develop` and working tree is clean
2. Run tests: `uv run pytest --tb=short -q`
3. Run lint/type checks: `uv run ruff check src/ tests/ && uv run mypy src/`
4. Ask user for the planned version number
5. Create release branch: `git checkout -b release/<version>`
6. Run: `uvx --from commitizen cz bump --yes --changelog --version-files-only`
7. Stage and commit: `git add pyproject.toml uv.lock CHANGELOG.md && git commit -m "chore: prepare release <version>"`
8. Remind user to:
   - Open PR from `release/<version>` into `main`
   - After merge, back-merge `main` into `develop`

Stop and ask for confirmation before each destructive or branching step.
