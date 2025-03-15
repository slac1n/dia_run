# Dia-Run

## Installation
```
uv sync
```

## Usage
Two steps are necessary currently:
1. Get Strava and Carelink data by executing `uv run src/dia_run/data.py`
2. Now fill out the questionnaire about the run `uv run src/dia_run/questionnaire.py`

**Note**: Right now, it only pulls the most recent Strava run and the last 24 hours of Carelink data.
This means that you should track your runs right after your workout.


## AWS Backup
```
aws s3 sync ./data s3://dia-run-bucket/ --profile personal --exclude "*/.DS_Store"
```
