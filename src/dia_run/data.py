from datetime import timedelta
from pathlib import Path
from typing import List, Tuple

import polars as pl
from loguru import logger

from dia_run.carelink_client import CareLinkClient
from dia_run.strava_client import authenticate_strava, stream_last_activity


class Data:
    def __init__(self):
        self.DATA_DIR = Path("data")
        self.STRAVA_SUMMARY_DIR = self.DATA_DIR / "strava" / "summary"
        self.STRAVA_STREAM_DIR = self.DATA_DIR / "strava" / "stream"
        self.CARELINK_DIR = self.DATA_DIR / "carelink"
        self.STRAVA_SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
        self.STRAVA_STREAM_DIR.mkdir(parents=True, exist_ok=True)
        self.CARELINK_DIR.mkdir(parents=True, exist_ok=True)
        self.latest_activity_id = None
        self.activity_id_list = self.get_activity_ids()

    def get_activity_ids(self) -> List[int]:
        # Check if a Delta table exists
        if not self.is_delta_table():
            return []

        # Load the Delta table using pl.scan_delta
        lf = pl.scan_delta(str(self.STRAVA_SUMMARY_DIR))

        # Get unique values of the 'activity_id' column
        unique_activity_ids = (
            lf.select(pl.col("activity_id").unique()).collect()["activity_id"].to_list()
        )

        return unique_activity_ids

    def is_delta_table(self) -> bool:
        """
        Check if a Delta table exists

        Returns
        -------
        bool
            True if a Delta table exists, False otherwise.
        """
        delta_log = self.STRAVA_SUMMARY_DIR / "_delta_log"
        return delta_log.is_dir()

    def get_strava_data(self) -> Tuple[pl.DataFrame | None, pl.DataFrame | None]:
        client = authenticate_strava()
        if not client:
            raise ValueError("Failed to authenticate Strava client")

        activity = stream_last_activity(client)
        if activity is None:
            raise ValueError("Failed to get latest activity")

        if activity.type != "Run":
            raise ValueError("Latest activity is not a run")

        self.latest_activity_id = activity.id

        if self.latest_activity_id is None:
            raise ValueError("Failed to get latest activity ID")

        if self.latest_activity_id in self.activity_id_list:
            logger.info(
                f"Activity with id={self.latest_activity_id} already exists in the data"
            )
            return None, None

        # Process Strava data for the latest activity
        df_summary, df_streams = self.process_latest_activity_id(client)

        return df_summary, df_streams

    def process_latest_activity_id(self, client) -> Tuple[pl.DataFrame, pl.DataFrame]:
        # Get detailed activity data
        da = client.get_activity(self.latest_activity_id)

        # Get activity streams for heart rate and power
        stream_types = ["heartrate", "watts", "velocity_smooth", "moving"]
        streams = client.get_activity_streams(
            self.latest_activity_id, types=stream_types, series_type="time"
        )

        df_summary = pl.DataFrame(
            {
                "activity_id": [self.latest_activity_id],
                "name": [da.name],
                "start_date_local": [da.start_date_local],
                "distance": [da.distance],
                "moving_time": [da.moving_time],
                "elapsed_time": [da.elapsed_time],
                "total_elevation_gain": [da.total_elevation_gain],
                "average_heartrate": [da.average_heartrate],
                "max_heartrate": [da.max_heartrate],
                "average_speed": [da.average_speed],
                "max_speed": [da.max_speed],
                "average_watts": [da.average_watts],
                "max_watts": [da.max_watts],
            }
        ).with_columns(
            pl.col("start_date_local").cast(pl.Datetime),
            ((1000 / pl.col("average_speed")) / 60).alias("average_pace"),
            ((1000 / pl.col("max_speed")) / 60).alias("max_pace"),
        )

        # Create a range of timestamps starting from the activity start time
        start_time_local = da.start_date_local
        timestamps = [
            start_time_local + timedelta(seconds=i) for i in streams["time"].data
        ]

        # Convert to Polars DataFrame
        df_streams = pl.DataFrame(
            {
                "datetime": timestamps,
                "heartrate": streams["heartrate"].data,
                "power": streams["watts"].data,
                "velocity": streams["velocity_smooth"].data,
                "moving": streams["moving"].data,
            }
        ).with_columns(
            pl.col("datetime").cast(pl.Datetime),
            pl.lit(self.latest_activity_id).alias("activity_id"),
            pl.when(pl.col("velocity") > 1)
            .then((1000 / pl.col("velocity")) / 60)
            .otherwise(None)
            .alias("pace"),
        )
        return (df_summary, df_streams)

    def get_carelink_data(self) -> pl.DataFrame | None:
        if self.latest_activity_id in self.activity_id_list:
            logger.info(
                f"Activity with id={self.latest_activity_id} already exists in the data"
            )
            return None

        client = CareLinkClient(tokenFile="logindata.json")
        if client.init():
            client.printUserInfo()
            carelink_data = client.getRecentData()
        else:
            raise ValueError("Failed to authenticate CareLink client")

        if carelink_data is None:
            raise ValueError("Failed to get CareLink data")

        if self.latest_activity_id is None:
            raise ValueError(
                "Failed to get latest activity ID. You need to get Strava data first."
            )

        # Convert to Polars DataFrame
        # sgs = sensor glucose aka cgm
        df = pl.DataFrame(carelink_data["patientData"]["sgs"])

        # add 'type' column with "CGM" value, rename and select
        df = (
            df.with_columns(pl.lit("CGM").alias("type"), pl.col("sg").cast(pl.Float64))
            .rename({"sg": "value"})
            .select(
                [
                    "timestamp",
                    "type",
                    "value",
                ]
            )
        )
        # Extract basal and bolus data
        marker_extraction = []
        for marker in carelink_data["patientData"]["markers"]:
            if marker["type"] == "AUTO_BASAL_DELIVERY":
                value = float(marker["data"]["dataValues"]["bolusAmount"])
            elif marker["type"] == "INSULIN":
                value = float(marker["data"]["dataValues"]["deliveredFastAmount"])
            else:
                value = None
            marker_extraction.append(
                {
                    "timestamp": marker["timestamp"],
                    "type": marker["type"],
                    "value": value,
                }
            )
        df_marker = pl.DataFrame(marker_extraction)

        # stack the two dataframes vertically
        df = df.vstack(df_marker)

        # Cast timestamp to datetime
        df = df.with_columns(
            pl.col("timestamp")
            .str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%S")
            .alias("datetime"),
            pl.lit(self.latest_activity_id).alias("activity_id"),
        ).drop("timestamp")

        return df


def get_latest_data_and_save(self):
    # Get Strava data
    logger.info("Getting Strava data...")
    strava_summary_data, strava_stream_data = self.get_strava_data()
    # Get CareLink data
    logger.info("Getting CareLink data...")
    carelink_data = self.get_carelink_data()

    # Save as delta tables
    if strava_summary_data is not None:
        logger.info("Saving strava summary data...")
        strava_summary_data.write_delta(self.STRAVA_SUMMARY_DIR, mode="append")
    if strava_stream_data is not None:
        logger.info("Saving strava stream data...")
        strava_stream_data.write_delta(self.STRAVA_STREAM_DIR, mode="append")
    if carelink_data is not None:
        logger.info("Saving carelink data...")
        carelink_data.write_delta(self.CARELINK_DIR, mode="append")


if __name__ == "__main__":
    data = Data()
    get_latest_data_and_save(data)
