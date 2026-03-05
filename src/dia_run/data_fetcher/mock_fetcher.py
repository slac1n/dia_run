import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
from loguru import logger

from dia_run.data_models.paths import DataPaths
from dia_run.data_models.schemas import SpecificCarelinkSchema


class MockDataFetcher:
    """Generates synthetic data and writes to Delta Lake tables. No real API calls are made."""

    def __init__(self, *, data_paths: DataPaths):
        self.STRAVA_SUMMARY_DIR: Path = data_paths.strava_summary
        self.STRAVA_STREAM_DIR: Path = data_paths.strava_stream
        self.CARELINK_DIR: Path = data_paths.carelink
        self.QUESTIONNAIRE_DIR: Path = data_paths.questionnaire
        self.STRAVA_SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
        self.STRAVA_STREAM_DIR.mkdir(parents=True, exist_ok=True)
        self.CARELINK_DIR.mkdir(parents=True, exist_ok=True)
        self.QUESTIONNAIRE_DIR.mkdir(parents=True, exist_ok=True)
        self.activity_id_list: list[int] = self._get_existing_activity_ids()

    def fetch_latest_data_and_save(self) -> None:
        activity_id = self._generate_activity_id()
        start_time = datetime.now().replace(second=0, microsecond=0) - timedelta(hours=1)
        duration_minutes = random.randint(25, 90)

        logger.info(f"[MOCK] Generating synthetic activity {activity_id}...")

        summary_df = self._generate_summary(
            activity_id=activity_id, start_time=start_time, duration_minutes=duration_minutes
        )
        stream_df = self._generate_streams(
            activity_id=activity_id, start_time=start_time, duration_minutes=duration_minutes
        )
        carelink_df = self._generate_carelink(
            activity_id=activity_id, start_time=start_time, duration_minutes=duration_minutes
        )

        logger.info("[MOCK] Saving strava summary data...")
        summary_df.write_delta(self.STRAVA_SUMMARY_DIR, mode="append", delta_write_options={"schema_mode": "merge"})

        logger.info("[MOCK] Validating carelink data...")
        SpecificCarelinkSchema.validate(carelink_df)
        logger.info("[MOCK] Saving carelink data...")
        carelink_df.write_delta(self.CARELINK_DIR, mode="append", delta_write_options={"schema_mode": "merge"})

        logger.info("[MOCK] Saving strava stream data...")
        stream_df.write_delta(self.STRAVA_STREAM_DIR, mode="append", delta_write_options={"schema_mode": "merge"})

        self._generate_questionnaire(activity_id=activity_id)
        logger.info(f"[MOCK] Successfully generated mock activity {activity_id}")

    def _get_existing_activity_ids(self) -> list[int]:
        delta_log = self.STRAVA_SUMMARY_DIR / "_delta_log"
        if not delta_log.is_dir():
            return []
        lf = pl.scan_delta(str(self.STRAVA_SUMMARY_DIR))
        ids: list[int] = lf.select(pl.col("activity_id").unique()).collect()["activity_id"].to_list()
        return ids

    def _generate_activity_id(self) -> int:
        if self.activity_id_list:
            return max(self.activity_id_list) + 1
        return 9000

    def _generate_summary(self, *, activity_id: int, start_time: datetime, duration_minutes: int) -> pl.DataFrame:
        distance = random.uniform(3000, 20000)
        moving_time = duration_minutes * 60
        avg_speed = distance / moving_time
        max_speed = avg_speed * random.uniform(1.1, 1.4)

        run_names = ["Easy Run", "Morning Jog", "Interval Session", "Long Run", "Tempo Run"]
        return pl.DataFrame(
            {
                "activity_id": [activity_id],
                "name": [random.choice(run_names)],
                "start_date_local": [start_time],
                "distance": [distance],
                "moving_time": [moving_time],
                "elapsed_time": [int(moving_time * random.uniform(1.0, 1.15))],
                "total_elevation_gain": [random.uniform(10, 200)],
                "average_heartrate": [random.uniform(135, 170)],
                "max_heartrate": [random.randint(170, 195)],
                "average_speed": [avg_speed],
                "max_speed": [max_speed],
                "average_watts": [random.uniform(130, 220)],
                "max_watts": [random.randint(220, 350)],
                "kilojoules": [random.uniform(200, 1200)],
            }
        ).with_columns(
            pl.col("start_date_local").cast(pl.Datetime),
            ((1000 / pl.col("average_speed")) / 60).alias("average_pace"),
            ((1000 / pl.col("max_speed")) / 60).alias("max_pace"),
        )

    def _generate_streams(self, *, activity_id: int, start_time: datetime, duration_minutes: int) -> pl.DataFrame:
        total_seconds = duration_minutes * 60
        timestamps = [start_time + timedelta(seconds=s) for s in range(total_seconds)]
        base_hr = random.randint(140, 160)
        base_velocity = random.uniform(2.2, 3.5)

        heartrates = [max(60, base_hr + random.randint(-10, 10)) for _ in range(total_seconds)]
        powers = [max(50, random.uniform(130, 220)) for _ in range(total_seconds)]
        velocities = [max(0.5, base_velocity + random.uniform(-0.5, 0.5)) for _ in range(total_seconds)]
        moving = [v > 1.0 for v in velocities]

        return pl.DataFrame(
            {
                "datetime": timestamps,
                "heartrate": heartrates,
                "power": powers,
                "velocity": velocities,
                "moving": moving,
            }
        ).with_columns(
            pl.col("datetime").cast(pl.Datetime),
            pl.lit(activity_id).alias("activity_id"),
            pl.when(pl.col("velocity") > 1).then((1000 / pl.col("velocity")) / 60).otherwise(None).alias("pace"),
        )

    def _generate_carelink(self, *, activity_id: int, start_time: datetime, duration_minutes: int) -> pl.DataFrame:
        data: list[dict[str, object]] = []

        # CGM readings every 5 minutes, starting 3 hours before and ending 30 min after the run
        cgm_start = start_time - timedelta(hours=3)
        cgm_end = start_time + timedelta(minutes=duration_minutes + 30)
        current = cgm_start
        base_glucose = random.uniform(120, 180)
        while current <= cgm_end:
            glucose = max(40.0, base_glucose + random.uniform(-15, 15))
            data.append(
                {
                    "datetime": current,
                    "type": "CGM",
                    "value": glucose,
                    "activity_id": activity_id,
                }
            )
            current += timedelta(minutes=5)

        # AUTO_BASAL_DELIVERY every 5 minutes for the pre-run window
        basal_current = start_time - timedelta(hours=3)
        while basal_current < start_time:
            data.append(
                {
                    "datetime": basal_current,
                    "type": "AUTO_BASAL_DELIVERY",
                    "value": round(random.uniform(0.1, 0.8), 2),
                    "activity_id": activity_id,
                }
            )
            basal_current += timedelta(minutes=5)

        # One INSULIN bolus before the run
        data.append(
            {
                "datetime": start_time - timedelta(minutes=random.randint(30, 120)),
                "type": "INSULIN",
                "value": round(random.uniform(0.5, 4.0), 1),
                "activity_id": activity_id,
            }
        )

        return pl.DataFrame(data).with_columns(pl.col("datetime").cast(pl.Datetime))

    def _generate_questionnaire(self, *, activity_id: int) -> None:
        questionnaire = {
            "pre_run": [
                {
                    "carbohydrates_g": random.choice([15, 20, 25, 30, 40]),
                    "time_before_start_min": -random.randint(15, 60),
                    "bolus_percentage": round(random.uniform(40, 80), 0),
                    "food_type": random.choice(["Energy Bar", "Banana", "Oatmeal", "Toast"]),
                }
            ],
            "basal_adjustments": [
                {
                    "type": random.choice(["Temporal SmartGuard", "Temporal Basalrate"]),
                    "start_time_min": -random.randint(10, 60),
                    "end_time_min": random.randint(30, 120),
                    "basal_rate_percentage": round(random.uniform(10, 50), 0),
                }
            ],
            "fueling_during_run": [
                {
                    "carbohydrates_g": random.choice([15, 20, 25]),
                    "time_during_run_min": random.randint(15, 45),
                    "food_type": random.choice(["Energy Gel", "Sports Drink", "Gummy Bears"]),
                }
            ],
            "bolus": [],
        }
        filepath = self.QUESTIONNAIRE_DIR / f"{activity_id}.json"
        with open(filepath, "w") as f:
            json.dump(questionnaire, f, indent=2)
        logger.info(f"[MOCK] Saved questionnaire to {filepath}")
