import json
from datetime import datetime, timedelta

import polars as pl
import pytest

from dia_run.data_models.paths import DataPaths
from dia_run.data_processing.data_processing import PRE_RUN_INSULIN_MINUTES


@pytest.fixture(scope="session")
def test_data_paths(tmp_path_factory: pytest.TempPathFactory) -> DataPaths:
    tmp_path = tmp_path_factory.getbasetemp()
    carelink_dir = tmp_path / "carelink"
    strava_summary_dir = tmp_path / "strava" / "summary"
    strava_stream_dir = tmp_path / "strava" / "stream"
    questionnaire_dir = tmp_path / "questionnaire"

    carelink_dir.mkdir(parents=True, exist_ok=True)
    strava_summary_dir.mkdir(parents=True, exist_ok=True)
    strava_stream_dir.mkdir(parents=True, exist_ok=True)
    questionnaire_dir.mkdir(parents=True, exist_ok=True)

    return DataPaths(
        carelink=carelink_dir,
        strava_summary=strava_summary_dir,
        strava_stream=strava_stream_dir,
        questionnaire=questionnaire_dir,
    )


@pytest.fixture(scope="session")
def strava_summary_data() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "activity_id": [1001, 1002, 1003],
            "name": ["Easy Run 5k", "Interval 8k", "Long Run 20k"],
            "start_date_local": [
                datetime(2025, 3, 25, 10, 0, 0),
                datetime(2025, 3, 26, 18, 0, 0),
                datetime(2025, 3, 27, 14, 0, 0),
            ],
            "elapsed_time": [1800, 3600, 7200],
            "distance": [5000, 8000, 20000],
            "average_pace": [5.5, 4.5, 6.0],
            "average_heartrate": [145, 165, 152],
        }
    )


@pytest.fixture(scope="session")
def carelink_data() -> pl.DataFrame:
    data = []
    activity_start_delta = -PRE_RUN_INSULIN_MINUTES - 60

    # Activity 1001 - Easy Run
    run_start = datetime(2025, 3, 25, 10, 0, 0)

    # Pre-run data (insulin)
    for i in range(activity_start_delta, 0, 5):
        data.append(
            {
                "activity_id": 1001,
                "datetime": run_start + timedelta(minutes=i),
                "type": "INSULIN" if i == -60 else "AUTO_BASAL_DELIVERY",
                "value": 2.0 if i == -60 else 0.5,
            }
        )

    # During run data (CGM)
    for i in range(activity_start_delta, 35, 5):
        data.append(
            {
                "activity_id": 1001,
                "datetime": run_start + timedelta(minutes=i),
                "type": "CGM",
                "value": 120.0 + i % 20,
            }
        )

    # Activity 1002 - Interval Training
    run_start = datetime(2025, 3, 26, 18, 0, 0)

    # Pre-run data (insulin)
    for i in range(activity_start_delta, 0, 5):
        data.append(
            {
                "activity_id": 1002,
                "datetime": run_start + timedelta(minutes=i),
                "type": "INSULIN" if i == -90 else "AUTO_BASAL_DELIVERY",
                "value": 1.5 if i == -90 else 0.3,
            }
        )

    # During run data (CGM)
    for i in range(activity_start_delta, 65, 5):
        value = 140.0 - (i / 10)
        if i == 30:
            value = 0.0
        data.append({"activity_id": 1002, "datetime": run_start + timedelta(minutes=i), "type": "CGM", "value": value})

    # Activity 1003 - Long Run
    run_start = datetime(2025, 3, 27, 14, 0, 0)

    # Pre-run data (insulin)
    for i in range(activity_start_delta, 0, 5):
        data.append(
            {
                "activity_id": 1003,
                "datetime": run_start + timedelta(minutes=i),
                "type": "INSULIN" if i == -120 else "AUTO_BASAL_DELIVERY",
                "value": 1.0 if i == -120 else 0.2,
            }
        )

    # During run data (CGM)
    for i in range(activity_start_delta, 125, 5):
        if i < 60:
            value = 170.0
        else:
            value = 170.0 - ((i - 60) / 5)
        data.append({"activity_id": 1003, "datetime": run_start + timedelta(minutes=i), "type": "CGM", "value": value})

    return pl.DataFrame(data)


@pytest.fixture(scope="session")
def strava_stream_data() -> pl.DataFrame:
    data = []

    # Activity 1001 - Easy Run
    for i in range(0, 30):
        data.append(
            {
                "activity_id": 1001,
                "heartrate": 140 + i % 10,
            }
        )

    # Activity 1002 - Interval Training
    for i in range(0, 60):
        if (i // 5) % 2 == 0:
            hr = 170 + i % 10
        else:
            hr = 150 + i % 10
        data.append({"activity_id": 1002, "heartrate": hr})

    # Activity 1003 - Long Run
    for i in range(0, 120):
        data.append(
            {
                "activity_id": 1003,
                "heartrate": 150 + i % 15,
            }
        )

    return pl.DataFrame(data)


@pytest.fixture(scope="session")
def questionnaire_data() -> dict[int, dict]:
    return {
        1001: {
            "pre_run": [],
            "basal_adjustments": [],
            "fueling_during_run": [],
            "bolus": [],
        },
        1002: {
            "pre_run": {
                "carbohydrates_g": "30",
                "time_before_start_min": "-30",
                "food_type": "Energy Bar",
                "bolus_percentage": "70",
            },
            "basal_adjustments": [
                {"type": "Temporal SmartGuard", "start_time_min": "-10", "end_time_min": "60"},
                {
                    "type": "Temporal Basalrate",
                    "start_time_min": "60",
                    "end_time_min": "120",
                    "basal_rate_percentage": "20",
                },
            ],
            "fueling_during_run": [{"carbohydrates_g": "15", "time_during_run_min": "15", "food_type": "Energy Gel"}],
            "bolus": {"time_of_bolus_min": "20", "bolus_units": "0.5"},
        },
        1003: {
            "pre_run": {
                "carbohydrates_g": "40",
                "time_before_start_min": "-60",
                "food_type": "Oatmeal",
                "bolus_percentage": "80",
            },
            "basal_adjustments": [],
            "fueling_during_run": [
                {"carbohydrates_g": "20", "time_during_run_min": "15", "food_type": "Energy Gel"},
                {"carbohydrates_g": "25", "time_during_run_min": "30", "food_type": "Sports Drink"},
            ],
            "bolus": [],
        },
    }


@pytest.fixture(scope="session", autouse=True)
def setup_test_data(
    *,
    test_data_paths: DataPaths,
    strava_summary_data: pl.DataFrame,
    carelink_data: pl.DataFrame,
    strava_stream_data: pl.DataFrame,
    questionnaire_data: dict[int, dict],
) -> None:
    strava_summary_data.write_delta(str(test_data_paths.strava_summary))
    carelink_data.write_delta(str(test_data_paths.carelink))
    strava_stream_data.write_delta(str(test_data_paths.strava_stream))
    for activity_id, data in questionnaire_data.items():
        with open(test_data_paths.questionnaire / f"{activity_id}.json", "w") as f:
            json.dump(data, f)
