from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import pandera.errors as pandera_errors
import polars as pl
from loguru import logger
from stravalib.client import Client

from dia_run.data_fetcher.carelink_client import CareLinkClient
from dia_run.data_fetcher.exceptions import CareLinkDataStaleError
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
        self.latest_activity_start_datetime: datetime | None = None
        self.latest_activity_end_datetime: datetime | None = None
        self.activity_id_list: list[int] = self._get_activity_ids()

    def fetch_latest_data_and_save(self) -> bool:
        self.latest_activity_start_datetime = None
        self.latest_activity_end_datetime = None
        logger.info("Fetching Strava data...")
        strava_summary_data, strava_stream_data = self._get_strava_data()
        logger.info("Fetching CareLink data...")
        carelink_data = self._get_carelink_data()

        if strava_summary_data is not None:
            logger.info("Saving strava summary data...")
            strava_summary_data.write_delta(self.STRAVA_SUMMARY_DIR, mode="append")
        if carelink_data is not None:
            logger.info("Saving carelink data...")
            carelink_data.write_delta(self.CARELINK_DIR, mode="append")
        if strava_stream_data is not None:
            if strava_stream_data.is_empty():
                logger.warning(
                    "No Strava stream rows available for activity {}. Skipping stream write.", self.latest_activity_id
                )
            else:
                logger.info("Saving strava stream data...")
                strava_stream_data.write_delta(self.STRAVA_STREAM_DIR, mode="append")

        return strava_summary_data is not None

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
        if da.start_date_local is None:
            raise ValueError("Activity start_date_local is None")

        start_time_local = da.start_date_local

        summary_data: dict[str, list[Any]] = {
            "activity_id": [self.latest_activity_id],
            "name": [str(da.name) if da.name is not None else ""],
            "start_date_local": [start_time_local],
            "distance": [float(da.distance) if da.distance is not None else 0.0],
            "moving_time": [int(da.moving_time) if da.moving_time is not None else 0],
            "elapsed_time": [int(da.elapsed_time) if da.elapsed_time is not None else 0],
            "total_elevation_gain": [float(da.total_elevation_gain) if da.total_elevation_gain is not None else 0.0],
            "average_heartrate": [float(da.average_heartrate) if da.average_heartrate is not None else None],
            "max_heartrate": [int(da.max_heartrate) if da.max_heartrate is not None else None],
            "average_speed": [float(da.average_speed) if da.average_speed is not None else None],
            "max_speed": [float(da.max_speed) if da.max_speed is not None else None],
            "average_watts": [float(da.average_watts) if da.average_watts is not None else None],
            "max_watts": [int(da.max_watts) if da.max_watts is not None else None],
            "kilojoules": [float(da.kilojoules) if da.kilojoules is not None else None],
        }

        StravaActivitySummary(
            id=int(da.id) if da.id is not None else 0,
            name=str(da.name) if da.name is not None else "",
            start_date_local=start_time_local,
            distance=float(da.distance) if da.distance is not None else 0.0,
            moving_time=int(da.moving_time) if da.moving_time is not None else 0,
            elapsed_time=int(da.elapsed_time) if da.elapsed_time is not None else 0,
            total_elevation_gain=float(da.total_elevation_gain) if da.total_elevation_gain is not None else 0.0,
            average_heartrate=float(da.average_heartrate) if da.average_heartrate is not None else None,
            max_heartrate=float(da.max_heartrate) if da.max_heartrate is not None else None,
            average_speed=float(da.average_speed) if da.average_speed is not None else None,
            max_speed=float(da.max_speed) if da.max_speed is not None else None,
            average_watts=float(da.average_watts) if da.average_watts is not None else None,
            max_watts=float(da.max_watts) if da.max_watts is not None else None,
            kilojoules=float(da.kilojoules) if da.kilojoules is not None else None,
        )

        stream_types = ["time", "heartrate", "watts", "velocity_smooth", "moving"]
        streams = client.get_activity_streams(self.latest_activity_id, types=stream_types, series_type="time")

        time_data = self._get_time_stream_values(streams=streams)
        if not time_data:
            logger.warning(
                "Strava activity {} is missing a usable time stream. Saving summary only.", self.latest_activity_id
            )
            return self._build_summary_dataframe(summary_data=summary_data), self._build_empty_stream_dataframe()

        heartrate_data = [
            int(value) if value is not None else None
            for value in self._get_optional_stream_values(
                streams=streams,
                stream_name="heartrate",
                expected_length=len(time_data),
            )
        ]
        watts_data = [
            float(value) if value is not None else None
            for value in self._get_optional_stream_values(
                streams=streams,
                stream_name="watts",
                expected_length=len(time_data),
            )
        ]
        velocity_data = [
            float(value) if value is not None else None
            for value in self._get_optional_stream_values(
                streams=streams,
                stream_name="velocity_smooth",
                expected_length=len(time_data),
            )
        ]
        moving_data = [
            bool(value) if value is not None else None
            for value in self._get_optional_stream_values(
                streams=streams,
                stream_name="moving",
                expected_length=len(time_data),
            )
        ]

        StravaStreamData(
            time=time_data,
            heartrate=heartrate_data,
            watts=watts_data,
            velocity_smooth=velocity_data,
            moving=moving_data,
        )

        df_summary = self._build_summary_dataframe(summary_data=summary_data)

        elapsed_time_seconds = int(da.elapsed_time) if da.elapsed_time is not None else 0
        self.latest_activity_start_datetime = start_time_local
        self.latest_activity_end_datetime = start_time_local + timedelta(seconds=elapsed_time_seconds)
        timestamps = [start_time_local + timedelta(seconds=i) for i in time_data]

        df_streams = pl.DataFrame(
            {
                "datetime": timestamps,
                "heartrate": heartrate_data,
                "power": watts_data,
                "velocity": velocity_data,
                "moving": moving_data,
            }
        ).with_columns(
            pl.col("datetime").cast(pl.Datetime),
            pl.col("heartrate").cast(pl.Int64),
            pl.col("power").cast(pl.Float64),
            pl.col("velocity").cast(pl.Float64),
            pl.col("moving").cast(pl.Boolean),
            pl.lit(self.latest_activity_id).cast(pl.Int64).alias("activity_id"),
            pl.when(pl.col("velocity").is_not_null() & (pl.col("velocity") > 1))
            .then((1000 / pl.col("velocity")) / 60)
            .otherwise(None)
            .alias("pace"),
        )
        return (df_summary, df_streams)

    def _build_summary_dataframe(self, *, summary_data: dict[str, list[Any]]) -> pl.DataFrame:
        return pl.DataFrame(summary_data).with_columns(
            pl.col("activity_id").cast(pl.Int64),
            pl.col("name").cast(pl.Utf8),
            pl.col("start_date_local").cast(pl.Datetime),
            pl.col("distance").cast(pl.Float64),
            pl.col("moving_time").cast(pl.Int64),
            pl.col("elapsed_time").cast(pl.Int64),
            pl.col("total_elevation_gain").cast(pl.Float64),
            pl.col("average_heartrate").cast(pl.Float64),
            pl.col("max_heartrate").cast(pl.Int64),
            pl.col("average_speed").cast(pl.Float64),
            pl.col("max_speed").cast(pl.Float64),
            pl.col("average_watts").cast(pl.Float64),
            pl.col("max_watts").cast(pl.Int64),
            pl.col("kilojoules").cast(pl.Float64),
            pl.when(pl.col("average_speed").is_not_null() & (pl.col("average_speed") > 0))
            .then((1000 / pl.col("average_speed")) / 60)
            .otherwise(None)
            .alias("average_pace"),
            pl.when(pl.col("max_speed").is_not_null() & (pl.col("max_speed") > 0))
            .then((1000 / pl.col("max_speed")) / 60)
            .otherwise(None)
            .alias("max_pace"),
        )

    def _build_empty_stream_dataframe(self) -> pl.DataFrame:
        return pl.DataFrame(
            schema={
                "datetime": pl.Datetime,
                "heartrate": pl.Int64,
                "power": pl.Float64,
                "velocity": pl.Float64,
                "moving": pl.Boolean,
                "activity_id": pl.Int64,
                "pace": pl.Float64,
            }
        )

    def _get_time_stream_values(self, *, streams: dict[str, Any]) -> list[int]:
        time_stream = streams.get("time")
        raw_data = cast(Sequence[Any] | None, getattr(time_stream, "data", None))

        if raw_data is None:
            return []

        return [int(value) for value in raw_data]

    def _get_optional_stream_values(
        self,
        *,
        streams: dict[str, Any],
        stream_name: str,
        expected_length: int,
    ) -> list[Any | None]:
        stream = streams.get(stream_name)
        raw_data = cast(Sequence[Any] | None, getattr(stream, "data", None))

        if stream is None:
            logger.info("Strava activity stream '{}' is missing for activity {}", stream_name, self.latest_activity_id)
            return [None] * expected_length

        if raw_data is None:
            logger.info("Strava activity stream '{}' has no data for activity {}", stream_name, self.latest_activity_id)
            return [None] * expected_length

        values = list(raw_data)
        if len(values) == expected_length:
            return values

        if len(values) > expected_length:
            logger.warning(
                "Strava activity stream '{}' has {} rows but time has {} for activity {}. Truncating.",
                stream_name,
                len(values),
                expected_length,
                self.latest_activity_id,
            )
            return values[:expected_length]

        logger.warning(
            "Strava activity stream '{}' has {} rows but time has {} for activity {}. Padding with nulls.",
            stream_name,
            len(values),
            expected_length,
            self.latest_activity_id,
        )
        return values + [None] * (expected_length - len(values))

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
            validated_carelink_data = CareLinkResponse(**carelink_data)
        except Exception as e:
            raise ValueError(f"CareLink API response validation failed: {e}") from e

        self._ensure_carelink_data_is_fresh(validated_carelink_data=validated_carelink_data)

        if self.latest_activity_id is None:
            raise ValueError("Failed to get latest activity ID. You need to get Strava data first.")

        carelink_rows: list[dict[str, datetime | float | int | None | str]] = []
        for reading in validated_carelink_data.patientData.sgs:
            carelink_rows.append(
                {
                    "datetime": self._parse_carelink_timestamp(raw_timestamp=reading.timestamp),
                    "type": "CGM",
                    "value": reading.sg,
                    "activity_id": self.latest_activity_id,
                }
            )

        for marker in validated_carelink_data.patientData.markers:
            marker_data = marker.model_dump()
            if marker_data["type"] == "AUTO_BASAL_DELIVERY":
                value = float(marker_data["data"]["dataValues"]["bolusAmount"])
            elif marker_data["type"] == "INSULIN":
                value = float(marker_data["data"]["dataValues"]["deliveredFastAmount"])
            else:
                value = None
            carelink_rows.append(
                {
                    "datetime": self._parse_carelink_timestamp(raw_timestamp=str(marker_data["timestamp"])),
                    "type": marker_data["type"],
                    "value": value,
                    "activity_id": self.latest_activity_id,
                }
            )

        df = pl.DataFrame(carelink_rows).with_columns(
            pl.col("datetime").cast(pl.Datetime),
            pl.col("value").cast(pl.Float64),
            pl.col("activity_id").cast(pl.Int64),
        )

        filtered_df = self._filter_carelink_data_to_activity_window(df=df)
        logger.info(
            "Filtered CareLink rows from {} to {} using a {} minute pre-window and {} minute post-window",
            len(df),
            len(filtered_df),
            settings.carelink_pre_workout_window_minutes,
            settings.carelink_post_workout_window_minutes,
        )

        logger.info("Validating carelink data...")
        try:
            SpecificCarelinkSchema.validate(filtered_df)
        except pandera_errors.SchemaError as e:
            raise ValueError(f"CareLink data validation failed: {e}") from e

        return filtered_df

    def _ensure_carelink_data_is_fresh(self, *, validated_carelink_data: CareLinkResponse) -> None:
        latest_cgm_raw_timestamp, latest_cgm_timestamp = self._get_latest_cgm_timestamp(
            validated_carelink_data=validated_carelink_data
        )
        current_server_time = self._get_current_server_time()
        staleness_age = current_server_time - latest_cgm_timestamp
        threshold = timedelta(minutes=settings.carelink_stale_threshold_minutes)
        is_stale = staleness_age > threshold

        logger.info(
            "CareLink staleness check result={} latest_cgm_raw_timestamp={} latest_cgm_timestamp={} "
            "current_server_time={} server_timezone={} threshold_minutes={} age_minutes={}",
            "stale" if is_stale else "fresh",
            latest_cgm_raw_timestamp,
            latest_cgm_timestamp.isoformat(),
            current_server_time.isoformat(),
            settings.server_timezone,
            settings.carelink_stale_threshold_minutes,
            round(staleness_age.total_seconds() / 60, 2),
        )

        if is_stale:
            raise CareLinkDataStaleError("CareLink data is out of date. Please retry later.")

    def _get_latest_cgm_timestamp(self, *, validated_carelink_data: CareLinkResponse) -> tuple[str, datetime]:
        latest_raw_timestamp: str | None = None
        latest_timestamp: datetime | None = None

        for reading in validated_carelink_data.patientData.sgs:
            parsed_timestamp = self._parse_carelink_timestamp(raw_timestamp=reading.timestamp)
            if latest_timestamp is None or parsed_timestamp > latest_timestamp:
                latest_timestamp = parsed_timestamp
                latest_raw_timestamp = reading.timestamp

        if latest_raw_timestamp is None or latest_timestamp is None:
            raise ValueError("CareLink API response did not include any CGM readings")

        return latest_raw_timestamp, latest_timestamp

    def _parse_carelink_timestamp(self, *, raw_timestamp: str) -> datetime:
        parsed_timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
        if parsed_timestamp.tzinfo is None:
            return parsed_timestamp
        return parsed_timestamp.astimezone(self._get_server_timezone()).replace(tzinfo=None)

    def _get_current_server_time(self) -> datetime:
        return datetime.now(tz=self._get_server_timezone()).replace(tzinfo=None)

    def _get_server_timezone(self) -> ZoneInfo:
        return ZoneInfo(settings.server_timezone)

    def _filter_carelink_data_to_activity_window(self, *, df: pl.DataFrame) -> pl.DataFrame:
        if self.latest_activity_start_datetime is None or self.latest_activity_end_datetime is None:
            raise ValueError("Failed to get activity timing. You need to get Strava data first.")

        window_start = self.latest_activity_start_datetime - timedelta(
            minutes=settings.carelink_pre_workout_window_minutes
        )
        window_end = self.latest_activity_end_datetime + timedelta(
            minutes=settings.carelink_post_workout_window_minutes
        )
        return df.filter((pl.col("datetime") >= window_start) & (pl.col("datetime") <= window_end))
