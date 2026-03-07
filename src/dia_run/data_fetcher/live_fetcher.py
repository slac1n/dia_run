from datetime import datetime, timedelta
from pathlib import Path

import pandera.errors as pandera_errors
import polars as pl
from loguru import logger
from stravalib.client import Client

from dia_run.data_fetcher.carelink_client import CareLinkClient
from dia_run.data_fetcher.strava_client import get_strava_client, stream_last_activity
from dia_run.data_models.api_responses import CareLinkResponse, StravaActivitySummary, StravaStreamData
from dia_run.data_models.paths import DataPaths
from dia_run.data_models.schemas import SpecificCarelinkSchema
from dia_run.settings import settings


class LiveDataFetcher:
    """Fetches real data from Strava and CareLink APIs and writes to Delta Lake tables."""

    def __init__(self, *, data_paths: DataPaths) -> None:
        self.STRAVA_SUMMARY_DIR: Path = data_paths.strava_summary
        self.STRAVA_STREAM_DIR: Path = data_paths.strava_stream
        self.CARELINK_DIR: Path = data_paths.carelink
        self.STRAVA_SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
        self.STRAVA_STREAM_DIR.mkdir(parents=True, exist_ok=True)
        self.CARELINK_DIR.mkdir(parents=True, exist_ok=True)
        self.latest_activity_id: int | None = None
        self.activity_id_list: list[int] = self._get_activity_ids()

    def fetch_latest_data_and_save(self) -> None:
        logger.info("Fetching Strava data...")
        strava_summary_data, strava_stream_data = self._get_strava_data()
        logger.info("Fetching CareLink data...")
        carelink_data = self._get_carelink_data()

        if strava_summary_data is not None:
            logger.info("Saving strava summary data...")
            strava_summary_data.write_delta(self.STRAVA_SUMMARY_DIR, mode="append")
        if carelink_data is not None:
            logger.info("Validating carelink data...")
            try:
                SpecificCarelinkSchema.validate(carelink_data)
            except pandera_errors.SchemaError as e:
                raise ValueError(f"CareLink data validation failed: {e}") from e
            logger.info("Saving carelink data...")
            carelink_data.write_delta(self.CARELINK_DIR, mode="append")
        if strava_stream_data is not None:
            logger.info("Saving strava stream data...")
            strava_stream_data.write_delta(self.STRAVA_STREAM_DIR, mode="append")

    def _get_activity_ids(self) -> list[int]:
        if not self._is_delta_table():
            return []
        lf = pl.scan_delta(str(self.STRAVA_SUMMARY_DIR))
        unique_activity_ids: list[int] = lf.select(pl.col("activity_id").unique()).collect()["activity_id"].to_list()
        return unique_activity_ids

    def _is_delta_table(self) -> bool:
        delta_log = self.STRAVA_SUMMARY_DIR / "_delta_log"
        return delta_log.is_dir()

    def _get_strava_data(self) -> tuple[pl.DataFrame | None, pl.DataFrame | None]:
        client = get_strava_client()
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
            logger.info(f"Activity with id={self.latest_activity_id} already exists in the data")
            return None, None

        df_summary, df_streams = self._process_latest_activity_id(client)
        return df_summary, df_streams

    def _process_latest_activity_id(self, client: Client) -> tuple[pl.DataFrame, pl.DataFrame]:
        if self.latest_activity_id is None:
            raise ValueError("Failed to get latest activity ID")

        da = client.get_activity(self.latest_activity_id)

        StravaActivitySummary(
            id=int(da.id) if da.id is not None else 0,
            name=str(da.name) if da.name is not None else "",
            start_date_local=da.start_date_local if da.start_date_local is not None else datetime.now(),
            distance=float(da.distance) if da.distance is not None else 0.0,
            moving_time=int(da.moving_time) if da.moving_time is not None else 0,
            elapsed_time=int(da.elapsed_time) if da.elapsed_time is not None else 0,
            total_elevation_gain=float(da.total_elevation_gain) if da.total_elevation_gain is not None else 0.0,
            average_heartrate=float(da.average_heartrate) if da.average_heartrate else None,
            max_heartrate=float(da.max_heartrate) if da.max_heartrate else None,
            average_speed=float(da.average_speed) if da.average_speed else None,
            max_speed=float(da.max_speed) if da.max_speed else None,
            average_watts=float(da.average_watts) if da.average_watts else None,
            max_watts=float(da.max_watts) if da.max_watts else None,
            kilojoules=float(da.kilojoules) if da.kilojoules else None,
        )

        stream_types = ["time", "heartrate", "watts", "velocity_smooth", "moving"]
        streams = client.get_activity_streams(self.latest_activity_id, types=stream_types, series_type="time")

        StravaStreamData(
            time=list(streams["time"].data) if streams["time"].data is not None else [],
            heartrate=list(streams["heartrate"].data) if streams["heartrate"].data is not None else [],
            watts=list(streams["watts"].data) if streams["watts"].data is not None else [],
            velocity_smooth=list(streams["velocity_smooth"].data)
            if streams["velocity_smooth"].data is not None
            else [],
            moving=list(streams["moving"].data) if streams["moving"].data is not None else [],
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
                "kilojoules": [da.kilojoules],
            }
        ).with_columns(
            pl.col("start_date_local").cast(pl.Datetime),
            ((1000 / pl.col("average_speed")) / 60).alias("average_pace"),
            ((1000 / pl.col("max_speed")) / 60).alias("max_pace"),
        )

        if da.start_date_local is None:
            raise ValueError("Activity start_date_local is None")
        start_time_local = da.start_date_local
        time_data = streams["time"].data if streams["time"].data is not None else []
        timestamps = [start_time_local + timedelta(seconds=i) for i in time_data]

        df_streams = pl.DataFrame(
            {
                "datetime": timestamps,
                "heartrate": streams["heartrate"].data if streams["heartrate"].data is not None else [],
                "power": streams["watts"].data if streams["watts"].data is not None else [],
                "velocity": streams["velocity_smooth"].data if streams["velocity_smooth"].data is not None else [],
                "moving": streams["moving"].data if streams["moving"].data is not None else [],
            }
        ).with_columns(
            pl.col("datetime").cast(pl.Datetime),
            pl.lit(self.latest_activity_id).alias("activity_id"),
            pl.when(pl.col("velocity") > 1).then((1000 / pl.col("velocity")) / 60).otherwise(None).alias("pace"),
        )
        return (df_summary, df_streams)

    def _get_carelink_data(self) -> pl.DataFrame | None:
        if self.latest_activity_id in self.activity_id_list:
            logger.info(f"Activity with id={self.latest_activity_id} already exists in the data")
            return None

        client = CareLinkClient(tokenFile=str(settings.carelink_token_file))
        if client.init():
            client.printUserInfo()
            carelink_data = client.getRecentData()
        else:
            raise ValueError("Failed to authenticate CareLink client")

        if carelink_data is None:
            raise ValueError("Failed to get CareLink data")

        try:
            CareLinkResponse(**carelink_data)
        except Exception as e:
            raise ValueError(f"CareLink API response validation failed: {e}") from e

        if self.latest_activity_id is None:
            raise ValueError("Failed to get latest activity ID. You need to get Strava data first.")

        df = pl.DataFrame(carelink_data["patientData"]["sgs"])

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

        df = df.vstack(df_marker)

        df = df.with_columns(
            pl.col("timestamp").str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%S").alias("datetime"),
            pl.lit(self.latest_activity_id).alias("activity_id"),
        ).drop("timestamp")

        return df
