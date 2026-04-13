Guide through the hotfix workflow for this project.

Prerequisites: must branch from `main`.

Steps:
1. Verify working tree is clean
2. Switch to main and pull: `git checkout main && git pull origin main`
3. Ask user for the hotfix description and planned version
4. Create hotfix branch: `git checkout -b hotfix/<version>`
5. After the user makes their fix, run:
   - `uv run pytest --tb=short -q`
   - `uv run ruff check src/ tests/ && uv run mypy src/`
6. Prepare release metadata: `uvx --from commitizen cz bump --yes --changelog --version-files-only`
7. Stage and commit: `git add pyproject.toml uv.lock CHANGELOG.md && git commit -m "chore: bump version for hotfix <version>"`
8. Remind user to:
   - Open PR from `hotfix/<version>` into `main`
   - After merge, back-merge `main` into `develop`

Stop and ask for confirmation before each destructive or branching step.
