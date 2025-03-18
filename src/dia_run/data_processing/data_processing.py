import json
from datetime import datetime

import polars as pl

from dia_run.data_models.paths import DataPaths
from dia_run.data_models.run_types import RunType


class DataProcessor:
    def __init__(self, data_paths: DataPaths | None = None):
        self.data_paths = data_paths or DataPaths()
        self.df_summary: pl.DataFrame | None = None

    def get_summary(self) -> pl.DataFrame:
        if self.df_summary is None:
            lf_summary = self._load_summary_data()
            lf_agg_glucose = self._aggregate_glucose(lf_summary)
            lf_summary = self._join_data(lf_left=lf_summary, lf_right=lf_agg_glucose)
            self.df_summary = lf_summary.collect()

        return self.df_summary

    def get_specific_carelink(
        self, *, activity_id: int, start_datetime: datetime, end_datetime: datetime
    ) -> pl.DataFrame:
        return (
            pl.scan_delta(str(self.data_paths.carelink))
            .filter(
                (pl.col("datetime") >= start_datetime - pl.duration(hours=2))
                & (pl.col("datetime") <= end_datetime + pl.duration(minutes=5))
                & (pl.col("activity_id") == activity_id)
            )
            .collect()
        )

    def get_questionnaire(self, activity_id: int) -> dict:
        with open(self.data_paths.questionnaire / f"{activity_id}.json") as f:
            return json.load(f)

    def get_heartrate_streams(self) -> pl.DataFrame:
        lf_summary = self._load_summary_data()
        return (
            pl.scan_delta(str(self.data_paths.strava_stream))
            .select(["heartrate", "activity_id"])
            .join(lf_summary.select(["activity_id", "run_type"]), on="activity_id", how="left")
            .select(pl.exclude("activity_id"))
        ).collect()

    def get_glucose_streams(self) -> pl.DataFrame:
        lf_summary = self._load_summary_data()
        return (
            self._load_glucose_data(lf_summary.select("activity_id", "start_date_local", "end_date_local", "run_type"))
            .select(pl.exclude(["activity_id", "start_date_local", "end_date_local"]))
            .collect()
        )

    def _load_summary_data(self) -> pl.LazyFrame:
        return pl.scan_delta(str(self.data_paths.strava_summary)).with_columns(
            pl.format(
                "{}:{}",
                (pl.col("elapsed_time") // 3600),  # Hours
                (pl.col("elapsed_time") % 3600) // 60,  # Minutes
            ).alias("human_readable_time"),
            pl.format(
                "{}:{}",
                (pl.col("average_pace").floor().cast(int)),  # Minutes
                ((pl.col("average_pace") % 1) * 60).round(0).cast(int),  # Fractional minutes to seconds
            ).alias("human_readable_pace"),
            pl.format(
                "{}",
                (pl.col("distance") / 1000).round(1),  # Convert meters to kilometers
            ).alias("distance_in_km"),
            (pl.col("start_date_local") + pl.duration(seconds=pl.col("elapsed_time"))).alias("end_date_local"),
            pl.format(
                "{} on {}",
                pl.col("name"),  # and only the date
                pl.col("start_date_local").dt.date(),
            ).alias("name_date"),
            pl.when(pl.col("name").str.contains(RunType.get_keyword(RunType.EASY)))
            .then(pl.lit(RunType.EASY))
            .when(pl.col("name").str.contains(RunType.get_keyword(RunType.INTERVAL)))
            .then(pl.lit(RunType.INTERVAL))
            .when(pl.col("name").str.contains(RunType.get_keyword(RunType.TEMPO)))
            .then(pl.lit(RunType.TEMPO))
            .when(pl.col("name").str.contains(RunType.get_keyword(RunType.LONG)))
            .then(pl.lit(RunType.LONG))
            .otherwise(pl.lit(RunType.OTHER))
            .alias("run_type"),
        )

    def _aggregate_glucose(self, lf_right: pl.LazyFrame) -> pl.LazyFrame:
        return (
            self._load_glucose_data(lf_right.select("activity_id", "start_date_local", "end_date_local"))
            .group_by("activity_id")
            .agg(
                [
                    pl.col("value").first().alias("in_going_sg"),
                    pl.col("value").last().alias("out_going_sg"),
                    pl.col("value").mean().alias("avg_sg"),
                ]
            )
        )

    def _load_glucose_data(self, lf_right: pl.LazyFrame) -> pl.LazyFrame:
        return (
            pl.scan_delta(str(self.data_paths.carelink))
            .filter(pl.col("type") == "CGM")
            .select(["value", "activity_id", "datetime"])
            .join(
                lf_right,
                on="activity_id",
                how="inner",
            )
            .filter(
                (pl.col("datetime") >= pl.col("start_date_local") - pl.duration(minutes=5))
                & (pl.col("datetime") <= pl.col("end_date_local") + pl.duration(minutes=5))
            )
        )

    def _join_data(self, *, lf_left: pl.LazyFrame, lf_right: pl.LazyFrame) -> pl.LazyFrame:
        return lf_left.join(
            lf_right,
            on="activity_id",
            how="left",
        )
