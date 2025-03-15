# Dia-Run

## Installation
```
uv sync
```

### Prepare Strava
You need to set up [Strava API](https://developers.strava.com/docs/getting-started/) for you account and create an app.
After that create a `.env` file and fill out the variables `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET` from your newly created app.

### Prepare Carelink
When using Dia-Run for the first time, run the setup for carelink `uv run src/dia_run/carelink_setup.py`.
This will require you to log in to your Carelink account and will automatically create a `logindata.json` file.
This file is valid for about a week.
If you are using Dia-Run regularly this file automatically gets updated. 
If you fail to use it within a week, you will need to recreate the file using the setup script.

## Usage
Two steps are required at this time:
1. Get Strava and Carelink data by executing `uv run src/dia_run/data.py`. 
Click on the Strava link providied in the termial and accept the request.
Now copy and paste the required part of the URL into the terminal.
2. Fill out the questionnaire about the run `uv run src/dia_run/questionnaire.py`

**Note**: Right now, it only pulls the most recent Strava run and the last 24 hours of Carelink data.
This means that you should track your runs right after your workout.


## AWS Backup
```
aws s3 sync ./data s3://dia-run-bucket/ --profile personal --exclude "*/.DS_Store"
```
