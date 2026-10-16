# Development Guide

## Branching Workflow

- Cut all feature branches from `develop`.
- Open feature PRs into `develop`; the `Tests` workflow runs there.
- Never merge feature branches directly into `develop`; always open and merge a PR into `develop`.
- Treat `main` as the production branch.
- When you are ready to ship, cut a `release/*` branch from `develop` and prepare the version and changelog there.
- Promote releases with a `release/*` -> `main` PR; that merge creates the final `v*` tag on `main`.
- Hotfixes branch from `main` as `hotfix/*`, open PRs back into `main`, and should be back-merged into `develop` after release.
- PRs into `main` must come from `release/*` or `hotfix/*`, include a version bump, update `uv.lock`, and update `CHANGELOG.md`.
- Do not push directly to `develop` or `main`.

### Feature Development

Start from the latest remote `develop` with a clean working tree:

```bash
git fetch origin --prune --tags
git switch -c codex/<feature-name> origin/develop
uv sync --frozen
```

Implement and test the feature, then run the checks before committing:

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
S3_SYNC_ENABLED=false uv run pytest
git add <changed-files>
git commit -m "feat: describe the feature"
git push -u origin HEAD
gh pr create --base develop
```

Ruff and mypy are used by the pre-commit configuration but are not declared in the `dev`
dependency group. They must be installed separately if `uv run` cannot find them.
Merge the feature PR after review and a successful `Tests` workflow. Version changes belong
on the subsequent release branch.

### Release Prep

When `develop` is ready to ship, create a release branch and prepare the release metadata there:

```bash
git fetch origin --prune --tags
git switch -c release/<planned-version> origin/develop
uvx --from commitizen cz bump --yes --changelog --version-files-only
git diff -- pyproject.toml uv.lock CHANGELOG.md
git add pyproject.toml uv.lock CHANGELOG.md
git commit -m "chore: prepare release"
git push -u origin HEAD
gh pr create --base main
```

Commitizen calculates the next version from conventional commits since the last release tag.
Check that the computed version matches the release branch name. A feature after `0.31.0`
normally produces `0.32.0`.

The PR must pass `Tests` and `Validate main promotion`. After merging it into `main`, wait
for `Tag release` to create `v<version>`. Use a merge commit to preserve release ancestry.
Then open and merge a PR from the same `release/*` branch into `develop` before deleting it.
Previous releases also used a separate back-merge branch from `main`; both paths keep release
metadata in `develop` without pushing directly to a protected branch.

### Deploy the Release to AWS

GitHub Actions runs tests, validates release metadata, and creates the version tag. It does
**not** build or deploy the production image. Docker images are built on Lightsail from the
checked-out source, and Docker Compose runs both `web` and the CareLink heartbeat `cron` service.

After the release tag exists, follow [the Lightsail deployment procedure](docs/lightsail_deployment.md#9-manual-deployment-workflow)
to deploy that exact version, verify health and the app footer, and record the previous version
for rollback. A successful GitHub release does not by itself update the running app.

### Hotfix Prep

For a `hotfix/*` branch, prepare the release metadata before opening the PR into `main`:

```bash
uvx --from commitizen cz bump --yes --changelog --version-files-only
git add pyproject.toml uv.lock CHANGELOG.md
git commit -m "chore: prepare hotfix release"
```

This keeps `main` clean while still ensuring every hotfix promotion lands with a releasable version and changelog.

## Mock Data Mode

Mock data mode lets you run the full application locally without real Strava or CareLink API credentials. No real API calls are made and the `./data` folder is completely untouched.

### Enabling Mock Mode

Set `USE_MOCK_DATA=true` in your `.env` file:

```bash
# .env
USE_MOCK_DATA=true
```

Then start the app as usual:

```bash
uv run uvicorn dia_run.web.app:app --reload
```

All views and features work identically — the switch is transparent to the frontend.

### How It Works

When `USE_MOCK_DATA=true`:

- **Data paths** are redirected from `./data/` to `./mock-data/` via the `get_data_paths()` dependency in `src/dia_run/web/dependencies.py`
- **Data fetching** uses `MockDataFetcher` instead of `LiveDataFetcher` — the "Download New Data" button generates a synthetic activity and appends it to the mock Delta tables
- **`DataProcessor`** reads from `./mock-data/` without any code changes (it only cares about `DataPaths`)
- **No production code** imports from `./mock-data/` directly — the switch is handled entirely through the DI layer

### Architecture

```
DataFetcherService (Protocol)
├── LiveDataFetcher  — real Strava + CareLink API calls
└── MockDataFetcher  — generates synthetic data, no API calls
```

The correct implementation is injected via `get_data_fetcher_service()` in `dependencies.py`, based on the `USE_MOCK_DATA` setting.

### Fixture Data

Pre-seeded mock data lives in `./mock-data/` and is committed to the repo. It contains 3 synthetic activities with matching Strava summary, stream, CareLink, and questionnaire data.

#### Regenerating Fixtures

To regenerate the mock data from scratch:

```bash
uv run python scripts/generate_mock_data.py
```

This will:
1. Delete the existing `./mock-data/` directory
2. Generate 3 synthetic activities (Easy Run, Interval, Long Run)
3. Write Delta Lake tables and questionnaire JSON files

The output should be committed to the repo so other developers can use mock mode without running the script.

### Adding New Fixture Activities

Edit `scripts/generate_mock_data.py` to add more activities or adjust the data shapes, then re-run the script and commit the updated `./mock-data/` directory.
