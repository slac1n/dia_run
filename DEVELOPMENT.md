# Development Guide

## Branching Workflow

- Cut all feature branches from `develop`.
- Open feature PRs into `develop`; the `Tests` workflow runs there.
- Treat `main` as the production branch.
- When you are ready to ship, cut a `release/*` branch from `develop` and prepare the version and changelog there.
- Promote releases with a `release/*` -> `main` PR; that merge creates the final `v*` tag on `main`.
- Hotfixes branch from `main` as `hotfix/*`, open PRs back into `main`, and should be back-merged into `develop` after release.
- PRs into `main` must come from `release/*` or `hotfix/*`, include a version bump, update `uv.lock`, and update `CHANGELOG.md`.
- Do not push directly to `develop` or `main`.

### Release Prep

When `develop` is ready to ship, create a release branch and prepare the release metadata there:

```bash
git checkout develop
git pull origin develop
git checkout -b release/<planned-version>
uvx --from commitizen cz bump --yes --changelog --version-files-only
git add pyproject.toml uv.lock CHANGELOG.md
git commit -m "chore: prepare release"
```

Open a PR from `release/*` into `main`, merge it once tests are green, and then merge the same `release/*` branch back into `develop`.

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
