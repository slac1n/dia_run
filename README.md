# Dia-Run :syringe::running:

## Installation
```bash
uv sync
```

### Pre-Commit Hooks
This project uses [pre-commit](https://pre-commit.com/) to run ruff (linting + formatting) and mypy (type checking) automatically before each commit. After installing dependencies, set up the hooks:
```bash
uv run pre-commit install
```

To run all hooks manually against the entire codebase:
```bash
uv run pre-commit run --all-files
```

### Prepare Strava
You need to set up [Strava API](https://developers.strava.com/docs/getting-started/) for you account and create an app.
After that create a `.env` file and fill out the variables `CLIENT_ID` and `CLIENT_SECRET` from your newly created app.
When fetching data for the first time, click on the Strava link provided in the terminal, log in and accept the authorization for downloading data from your account.

### Prepare Carelink
When using Dia-Run for the first time, run the setup for carelink `uv run src/dia_run/carelink_setup.py`.
This will require you to log in to your Carelink account and will automatically create a `logindata.json` file.
This file is valid for about a week.
If you are using Dia-Run regularly this file automatically gets updated. 
If you fail to use it within a week, you will need to recreate the file using the setup script.

## Usage
To get your latest data:
1. Run `uv run fetch` to download Strava and Carelink data
2. Afterwards you will be prompted to fill out the questionnaire about the run (basal setting, pre-run nutrition, fueling, and bolusing)

**Note**: Right now, it only pulls the most recent Strava workout and the last 24 hours of Carelink data.
This means that you should track your runs right after your workout.

Start the dashboard by running:
```bash
uv run streamlit run src/dia_run/dashboard/app.py
```

## AWS Backup
```
aws s3 sync ./data s3://dia-run-bucket/ --profile personal --exclude "*/.DS_Store"
```
