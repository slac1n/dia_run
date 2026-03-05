#!/usr/bin/env python3
"""Generate pre-seeded mock Delta Lake tables for local development.

Usage:
    uv run python scripts/generate_mock_data.py

This creates realistic fixture data in ./mock-data/ with 3 synthetic activities
and matching CareLink, stream, and questionnaire data. The output is committed
to the repo and used when USE_MOCK_DATA=true.
"""

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl

MOCK_DATA_DIR = Path("mock-data")
STRAVA_SUMMARY_DIR = MOCK_DATA_DIR / "strava" / "summary"
STRAVA_STREAM_DIR = MOCK_DATA_DIR / "strava" / "stream"
CARELINK_DIR = MOCK_DATA_DIR / "carelink"
QUESTIONNAIRE_DIR = MOCK_DATA_DIR / "run_questionnaires"

PRE_RUN_INSULIN_MINUTES = 180


def generate_strava_summary() -> pl.DataFrame:
    """Generate 3 synthetic Strava activity summaries."""
    return pl.DataFrame(
        {
            "activity_id": [5001, 5002, 5003],
            "name": ["Easy Run 5k", "Interval 8x400m", "Long Run 18k"],
            "start_date_local": [
                datetime(2025, 6, 10, 7, 30, 0),
                datetime(2025, 6, 12, 18, 0, 0),
                datetime(2025, 6, 15, 8, 0, 0),
            ],
            "distance": [5200.0, 8500.0, 18200.0],
            "moving_time": [1680, 2700, 5760],
            "elapsed_time": [1740, 2880, 5940],
            "total_elevation_gain": [35.0, 72.0, 145.0],
            "average_heartrate": [142.0, 168.0, 153.0],
            "max_heartrate": [158.0, 188.0, 172.0],
            "average_speed": [3.1, 3.15, 3.16],
            "max_speed": [3.6, 5.2, 3.8],
            "average_watts": [155.0, 210.0, 180.0],
            "max_watts": [195.0, 310.0, 245.0],
            "kilojoules": [420.0, 680.0, 1050.0],
        }
    ).with_columns(
        pl.col("start_date_local").cast(pl.Datetime),
        ((1000 / pl.col("average_speed")) / 60).alias("average_pace"),
        ((1000 / pl.col("max_speed")) / 60).alias("max_pace"),
    )


def generate_strava_streams() -> pl.DataFrame:
    """Generate per-second stream data for each activity."""
    data = []

    # Activity 5001 — Easy Run, 28 min
    run_start = datetime(2025, 6, 10, 7, 30, 0)
    for i in range(1680):
        data.append(
            {
                "datetime": run_start + timedelta(seconds=i),
                "activity_id": 5001,
                "heartrate": 135 + (i % 15),
                "power": 145.0 + (i % 20),
                "velocity": 3.0 + 0.2 * ((i % 60) / 60),
                "moving": True,
            }
        )

    # Activity 5002 — Interval session, 45 min
    run_start = datetime(2025, 6, 12, 18, 0, 0)
    for i in range(2700):
        interval_block = (i // 180) % 2 == 0
        if interval_block:
            hr = 175 + (i % 13)
            vel = 4.5 + 0.3 * ((i % 30) / 30)
        else:
            hr = 145 + (i % 10)
            vel = 2.5 + 0.1 * ((i % 30) / 30)
        data.append(
            {
                "datetime": run_start + timedelta(seconds=i),
                "activity_id": 5002,
                "heartrate": hr,
                "power": 160.0 + (hr - 145) * 1.5,
                "velocity": vel,
                "moving": True,
            }
        )

    # Activity 5003 — Long Run, 96 min
    run_start = datetime(2025, 6, 15, 8, 0, 0)
    for i in range(5760):
        # Gradual cardiac drift
        drift = i / 5760 * 15
        data.append(
            {
                "datetime": run_start + timedelta(seconds=i),
                "activity_id": 5003,
                "heartrate": int(148 + drift + (i % 8)),
                "power": 170.0 + (i % 25),
                "velocity": 3.1 + 0.15 * ((i % 120) / 120),
                "moving": True,
            }
        )

    return pl.DataFrame(data).with_columns(
        pl.col("datetime").cast(pl.Datetime),
        pl.when(pl.col("velocity") > 1).then((1000 / pl.col("velocity")) / 60).otherwise(None).alias("pace"),
    )


def generate_carelink() -> pl.DataFrame:
    """Generate CGM + insulin data for each activity."""
    data = []
    activity_start_delta = -PRE_RUN_INSULIN_MINUTES - 60

    # Activity 5001 — Easy Run
    run_start = datetime(2025, 6, 10, 7, 30, 0)
    for i in range(activity_start_delta, 0, 5):
        data.append(
            {
                "activity_id": 5001,
                "datetime": run_start + timedelta(minutes=i),
                "type": "INSULIN" if i == -60 else "AUTO_BASAL_DELIVERY",
                "value": 1.5 if i == -60 else 0.4,
            }
        )
    for i in range(activity_start_delta, 35, 5):
        data.append(
            {
                "activity_id": 5001,
                "datetime": run_start + timedelta(minutes=i),
                "type": "CGM",
                "value": 135.0 + (i % 20) - 5,
            }
        )

    # Activity 5002 — Interval
    run_start = datetime(2025, 6, 12, 18, 0, 0)
    for i in range(activity_start_delta, 0, 5):
        data.append(
            {
                "activity_id": 5002,
                "datetime": run_start + timedelta(minutes=i),
                "type": "INSULIN" if i == -90 else "AUTO_BASAL_DELIVERY",
                "value": 2.0 if i == -90 else 0.35,
            }
        )
    for i in range(activity_start_delta, 50, 5):
        data.append(
            {
                "activity_id": 5002,
                "datetime": run_start + timedelta(minutes=i),
                "type": "CGM",
                "value": 155.0 - (i / 8),
            }
        )
    # Post-run CGM for fueling impact
    for i in range(55, 130, 5):
        if i <= 90:
            value = 140.0 + (i - 55) * 1.2
        else:
            value = 182.0 - (i - 90) * 0.6
        data.append({"activity_id": 5002, "datetime": run_start + timedelta(minutes=i), "type": "CGM", "value": value})

    # Activity 5003 — Long Run
    run_start = datetime(2025, 6, 15, 8, 0, 0)
    for i in range(activity_start_delta, 0, 5):
        data.append(
            {
                "activity_id": 5003,
                "datetime": run_start + timedelta(minutes=i),
                "type": "INSULIN" if i == -120 else "AUTO_BASAL_DELIVERY",
                "value": 1.0 if i == -120 else 0.25,
            }
        )
    for i in range(activity_start_delta, 100, 5):
        if i < 50:
            value = 165.0
        else:
            value = 165.0 - ((i - 50) / 4)
        data.append({"activity_id": 5003, "datetime": run_start + timedelta(minutes=i), "type": "CGM", "value": value})
    # Post-run CGM
    for i in range(100, 160, 5):
        if i <= 130:
            value = 152.0 + (i - 100) * 2.5
        else:
            value = 227.0 - (i - 130) * 1.8
        data.append({"activity_id": 5003, "datetime": run_start + timedelta(minutes=i), "type": "CGM", "value": value})

    return pl.DataFrame(data).with_columns(pl.col("datetime").cast(pl.Datetime))


def generate_questionnaires() -> dict[int, dict]:
    """Generate questionnaire JSON files for each activity."""
    return {
        5001: {
            "pre_run": [
                {
                    "carbohydrates_g": 20,
                    "time_before_start_min": -30,
                    "bolus_percentage": 50.0,
                    "food_type": "Banana",
                }
            ],
            "basal_adjustments": [{"type": "Temporal SmartGuard", "start_time_min": -15, "end_time_min": 30}],
            "fueling_during_run": [],
            "bolus": [],
        },
        5002: {
            "pre_run": [
                {
                    "carbohydrates_g": 35,
                    "time_before_start_min": -45,
                    "bolus_percentage": 65.0,
                    "food_type": "Energy Bar",
                }
            ],
            "basal_adjustments": [
                {"type": "Temporal SmartGuard", "start_time_min": -10, "end_time_min": 50},
                {
                    "type": "Temporal Basalrate",
                    "start_time_min": 50,
                    "end_time_min": 120,
                    "basal_rate_percentage": 25.0,
                },
            ],
            "fueling_during_run": [{"carbohydrates_g": 20, "time_during_run_min": 20, "food_type": "Energy Gel"}],
            "bolus": [{"time_of_bolus_min": 25, "bolus_units": 0.5}],
        },
        5003: {
            "pre_run": [
                {
                    "carbohydrates_g": 50,
                    "time_before_start_min": -60,
                    "bolus_percentage": 70.0,
                    "food_type": "Oatmeal",
                }
            ],
            "basal_adjustments": [
                {
                    "type": "Temporal Basalrate",
                    "start_time_min": -30,
                    "end_time_min": 100,
                    "basal_rate_percentage": 20.0,
                }
            ],
            "fueling_during_run": [
                {"carbohydrates_g": 25, "time_during_run_min": 25, "food_type": "Energy Gel"},
                {"carbohydrates_g": 25, "time_during_run_min": 50, "food_type": "Sports Drink"},
            ],
            "bolus": [],
        },
    }


def main() -> None:
    """Generate all mock data and write to ./mock-data/."""
    # Clean previous mock data
    if MOCK_DATA_DIR.exists():
        shutil.rmtree(MOCK_DATA_DIR)

    STRAVA_SUMMARY_DIR.mkdir(parents=True)
    STRAVA_STREAM_DIR.mkdir(parents=True)
    CARELINK_DIR.mkdir(parents=True)
    QUESTIONNAIRE_DIR.mkdir(parents=True)

    print("Generating Strava summary data...")
    summary = generate_strava_summary()
    summary.write_delta(str(STRAVA_SUMMARY_DIR))
    print(f"  -> {len(summary)} rows written to {STRAVA_SUMMARY_DIR}")

    print("Generating Strava stream data...")
    streams = generate_strava_streams()
    streams.write_delta(str(STRAVA_STREAM_DIR))
    print(f"  -> {len(streams)} rows written to {STRAVA_STREAM_DIR}")

    print("Generating CareLink data...")
    carelink = generate_carelink()
    carelink.write_delta(str(CARELINK_DIR))
    print(f"  -> {len(carelink)} rows written to {CARELINK_DIR}")

    print("Generating questionnaire data...")
    questionnaires = generate_questionnaires()
    for activity_id, data in questionnaires.items():
        filepath = QUESTIONNAIRE_DIR / f"{activity_id}.json"
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        print(f"  -> Written {filepath}")

    print(f"\nDone! Mock data generated in {MOCK_DATA_DIR}/")
    print("Activities: 5001 (Easy Run), 5002 (Interval), 5003 (Long Run)")


if __name__ == "__main__":
    main()
