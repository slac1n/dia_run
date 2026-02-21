import json
from datetime import datetime, timedelta
from typing import TypeVar

import polars as pl
from pandera import check_types
from pandera.typing.polars import DataFrame, LazyFrame

from dia_run.data_models.constants import TARGET_GLUCOSE_LOWER, TARGET_GLUCOSE_UPPER
from dia_run.data_models.kpis import KpiModel
from dia_run.data_models.paths import DataPaths
from dia_run.data_models.questionnaire import QuestionnaireModel
from dia_run.data_models.run_types import RunType
from dia_run.data_models.schemas import (
    AggregatedGlucoseSchema,
    AggregateInsulinOnBoard,
    BaseGlucoseStreamSchema,
    FuelingGlucoseWindowSchema,
    FuelingImpactSchema,
    GlucoseStreamsSchema,
    HeartrateStreamsSchema,
    PreRunInsulinSchema,
    PreRunNutritionSummarySchema,
    SpecificCarelinkSchema,
    StravaSummarySchema,
    SummarySchema,
)

T = TypeVar("T")
U = TypeVar("U")
V = TypeVar("V")
PRE_RUN_INSULIN_MINUTES = 180


class DataProcessor:
    def __init__(self, data_paths: DataPaths | None = None):
        self.data_paths = data_paths or DataPaths()
        self.df_summary: pl.DataFrame | None = None

    @check_types
    def get_summary(self) -> DataFrame[SummarySchema]:
        if self.df_summary is None:
            lf_summary = self._load_summary_data()
            lf_agg_glucose = self._aggregate_glucose(lf_summary)
            lf_agg_insulin_on_board = self._aggregate_insulin_on_board(lf_summary)
            lf_summary = self._join_data(lf_left=lf_summary, lf_right=lf_agg_glucose)
            lf_summary = self._join_data(lf_left=lf_summary, lf_right=lf_agg_insulin_on_board)
            self.df_summary = lf_summary.collect()

        return self.df_summary

    def get_30_day_kpis(self, *, reference_date: datetime | None = None) -> KpiModel:
        self.get_summary()
        reference = reference_date or datetime.now()
        cutoff = reference - timedelta(days=30)

        df_recent = self.df_summary.filter(pl.col("start_date_local") >= cutoff)  # type: ignore[union-attr]

        total_distance_km = round(df_recent["distance"].sum() / 1000, 1)
        total_running_time_minutes = int(df_recent["moving_time"].sum() // 60)

        df_with_glucose = df_recent.drop_nulls(subset=["avg_sg", "moving_time"])
        if df_with_glucose.is_empty():
            avg_sensor_glucose = None
            time_in_range_percentage = None
        else:
            total_moving_time = df_with_glucose["moving_time"].sum()
            if total_moving_time == 0:
                avg_sensor_glucose = None
                time_in_range_percentage = None
            else:
                avg_sensor_glucose = round(
                    (df_with_glucose["avg_sg"] * df_with_glucose["moving_time"]).sum() / total_moving_time,
                    1,
                )  # type: ignore[arg-type]
                time_in_range_seconds = df_with_glucose.filter(
                    (pl.col("avg_sg") >= TARGET_GLUCOSE_LOWER) & (pl.col("avg_sg") <= TARGET_GLUCOSE_UPPER)
                )["moving_time"].sum()
                time_in_range_percentage = round(time_in_range_seconds / total_moving_time * 100, 1)

        return KpiModel(
            total_distance_km=total_distance_km,
            total_running_time_minutes=total_running_time_minutes,
            avg_sensor_glucose=avg_sensor_glucose,
            time_in_range_percentage=time_in_range_percentage,
        )

    @check_types
    def get_specific_carelink(
        self, *, activity_id: int, start_datetime: datetime, end_datetime: datetime
    ) -> DataFrame[SpecificCarelinkSchema]:
        return (
            pl.scan_delta(str(self.data_paths.carelink))
            .filter(
                (pl.col("datetime") >= start_datetime - pl.duration(minutes=PRE_RUN_INSULIN_MINUTES))
                & (pl.col("datetime") <= end_datetime + pl.duration(minutes=5))
                & (pl.col("activity_id") == activity_id)
                & (pl.col("type").is_in(["CGM", "AUTO_BASAL_DELIVERY", "INSULIN"]))
            )
            .with_columns(
                pl.when(pl.col("type") == "CGM")
                .then(pl.col("value").replace(0.0, None))
                .otherwise(pl.col("value"))
                .alias("value")
            )
            .drop("activity_id")
            .collect()
        )

    def get_questionnaire(self, activity_id: int) -> QuestionnaireModel:
        with open(self.data_paths.questionnaire / f"{activity_id}.json") as f:
            data = json.load(f)
        return QuestionnaireModel.model_validate(data)

    @check_types
    def get_pre_run_nutrition_summary(self) -> DataFrame[PreRunNutritionSummarySchema]:
        df_summary = self.get_summary()
        nutrition_rows: list[dict[str, int | float | str]] = []

        for row in df_summary.iter_rows(named=True):
            activity_id: int = row["activity_id"]
            in_going_sg = row["in_going_sg"]
            name_date: str = row["name_date"]

            if in_going_sg is None:
                continue

            questionnaire_path = self.data_paths.questionnaire / f"{activity_id}.json"
            if not questionnaire_path.exists():
                continue

            questionnaire = self.get_questionnaire(activity_id)
            if not questionnaire.pre_run:
                continue

            total_carbs = sum(entry.carbohydrates_g for entry in questionnaire.pre_run)
            earliest_timing = min(entry.time_before_start_min for entry in questionnaire.pre_run)
            avg_bolus = sum(entry.bolus_percentage for entry in questionnaire.pre_run) / len(questionnaire.pre_run)

            nutrition_rows.append(
                {
                    "activity_id": activity_id,
                    "total_carbohydrates_g": total_carbs,
                    "earliest_time_before_start_min": earliest_timing,
                    "avg_bolus_percentage": avg_bolus,
                    "in_going_sg": in_going_sg,
                    "name_date": name_date,
                }
            )

        if not nutrition_rows:
            return pl.DataFrame(
                schema={
                    "activity_id": pl.Int64,
                    "total_carbohydrates_g": pl.Int64,
                    "earliest_time_before_start_min": pl.Int64,
                    "avg_bolus_percentage": pl.Float64,
                    "in_going_sg": pl.Float64,
                    "name_date": pl.Utf8,
                }
            )

        return pl.DataFrame(nutrition_rows)

    @check_types
    def get_heartrate_streams(self) -> DataFrame[HeartrateStreamsSchema]:
        lf_summary = self._load_summary_data()
        return (
            pl.scan_delta(str(self.data_paths.strava_stream))
            .select(["datetime", "heartrate", "activity_id"])
            .join(lf_summary.select(["activity_id", "run_type"]), on="activity_id", how="left")
            .select(pl.exclude("activity_id"))
        ).collect()

    @check_types
    def get_glucose_streams(self) -> DataFrame[GlucoseStreamsSchema]:
        lf_summary = self._load_summary_data()
        return self._load_glucose_data(lf_summary).drop("activity_id").collect()

    FUELING_WINDOW_MINUTES = 45
    PRE_INTAKE_WINDOW_MINUTES = 15

    @check_types
    def get_fueling_glucose_windows(self) -> DataFrame[FuelingGlucoseWindowSchema]:
        df_summary = self.get_summary()
        window_rows: list[dict[str, int | float | None]] = []

        for row in df_summary.iter_rows(named=True):
            activity_id: int = row["activity_id"]
            start_date_local: datetime = row["start_date_local"]
            end_date_local: datetime = row["end_date_local"]

            questionnaire_path = self.data_paths.questionnaire / f"{activity_id}.json"
            if not questionnaire_path.exists():
                continue

            questionnaire = self.get_questionnaire(activity_id)
            if not questionnaire.fueling_during_run:
                continue

            df_cgm = (
                pl.scan_delta(str(self.data_paths.carelink))
                .filter((pl.col("type") == "CGM") & (pl.col("activity_id") == activity_id))
                .select(["datetime", "value"])
                .with_columns(pl.col("value").replace(0.0, None))
                .sort("datetime")
                .collect()
            )

            if df_cgm.is_empty():
                continue

            fueling_list = questionnaire.fueling_during_run
            for fueling_index, fueling in enumerate(fueling_list):
                fueling_datetime = start_date_local + timedelta(minutes=fueling.time_during_run_min)
                window_start = fueling_datetime - timedelta(minutes=self.PRE_INTAKE_WINDOW_MINUTES)
                window_end = fueling_datetime + timedelta(minutes=self.FUELING_WINDOW_MINUTES)

                # Clamp window to activity bounds (no pre/post activity data)
                window_start = max(window_start, start_date_local)
                window_end = min(window_end, end_date_local)

                # Truncate at next intake time so windows don't overlap
                if fueling_index + 1 < len(fueling_list):
                    next_fueling_datetime = start_date_local + timedelta(
                        minutes=fueling_list[fueling_index + 1].time_during_run_min
                    )
                    window_end = min(window_end, next_fueling_datetime)

                df_window = df_cgm.filter((pl.col("datetime") >= window_start) & (pl.col("datetime") <= window_end))

                for cgm_row in df_window.iter_rows(named=True):
                    minutes_rel = (cgm_row["datetime"] - fueling_datetime).total_seconds() / 60.0
                    window_rows.append(
                        {
                            "activity_id": activity_id,
                            "fueling_index": fueling_index,
                            "minutes_relative": minutes_rel,
                            "value": cgm_row["value"],
                        }
                    )

        if not window_rows:
            return pl.DataFrame(
                schema={
                    "activity_id": pl.Int64,
                    "fueling_index": pl.Int64,
                    "minutes_relative": pl.Float64,
                    "value": pl.Float64,
                }
            )

        return pl.DataFrame(window_rows)

    @check_types
    def get_fueling_impact(self) -> DataFrame[FuelingImpactSchema]:
        df_summary = self.get_summary()
        df_windows = self.get_fueling_glucose_windows()
        impact_rows: list[dict[str, object]] = []

        for row in df_summary.iter_rows(named=True):
            activity_id: int = row["activity_id"]
            start_date_local: datetime = row["start_date_local"]
            name_date: str = row["name_date"]

            questionnaire_path = self.data_paths.questionnaire / f"{activity_id}.json"
            if not questionnaire_path.exists():
                continue

            questionnaire = self.get_questionnaire(activity_id)
            if not questionnaire.fueling_during_run:
                continue

            for fueling_index, fueling in enumerate(questionnaire.fueling_during_run):
                df_event = df_windows.filter(
                    (pl.col("activity_id") == activity_id) & (pl.col("fueling_index") == fueling_index)
                ).sort("minutes_relative")

                baseline_sg = self._get_baseline_glucose(
                    activity_id=activity_id,
                    fueling_datetime=start_date_local + timedelta(minutes=fueling.time_during_run_min),
                )

                if df_event.drop_nulls("value").is_empty() or baseline_sg is None:
                    impact_rows.append(
                        {
                            "activity_id": activity_id,
                            "fueling_index": fueling_index,
                            "carbohydrates_g": fueling.carbohydrates_g,
                            "baseline_sg": baseline_sg,
                            "peak_sg": None,
                            "peak_increase": None,
                            "time_to_peak_min": None,
                            "name_date": name_date,
                        }
                    )
                    continue

                df_valid = df_event.drop_nulls("value")
                peak_sg = df_valid["value"].max()
                peak_increase = peak_sg - baseline_sg  # type: ignore[operator]
                peak_row = df_valid.filter(pl.col("value") == peak_sg).head(1)
                time_to_peak_min = peak_row["minutes_relative"].item()

                impact_rows.append(
                    {
                        "activity_id": activity_id,
                        "fueling_index": fueling_index,
                        "carbohydrates_g": fueling.carbohydrates_g,
                        "baseline_sg": baseline_sg,
                        "peak_sg": peak_sg,
                        "peak_increase": peak_increase,
                        "time_to_peak_min": time_to_peak_min,
                        "name_date": name_date,
                    }
                )

        if not impact_rows:
            return pl.DataFrame(
                schema={
                    "activity_id": pl.Int64,
                    "fueling_index": pl.Int64,
                    "carbohydrates_g": pl.Int64,
                    "baseline_sg": pl.Float64,
                    "peak_sg": pl.Float64,
                    "peak_increase": pl.Float64,
                    "time_to_peak_min": pl.Float64,
                    "name_date": pl.Utf8,
                }
            )

        return pl.DataFrame(impact_rows).cast(
            {
                "baseline_sg": pl.Float64,
                "peak_sg": pl.Float64,
                "peak_increase": pl.Float64,
                "time_to_peak_min": pl.Float64,
            }
        )

    def _get_baseline_glucose(self, *, activity_id: int, fueling_datetime: datetime) -> float | None:
        df_cgm = (
            pl.scan_delta(str(self.data_paths.carelink))
            .filter((pl.col("type") == "CGM") & (pl.col("activity_id") == activity_id))
            .select(["datetime", "value"])
            .with_columns(pl.col("value").replace(0.0, None))
            .collect()
            .drop_nulls("value")
        )

        if df_cgm.is_empty():
            return None

        df_cgm = df_cgm.with_columns(
            (pl.col("datetime") - fueling_datetime).dt.total_seconds().abs().alias("time_diff")
        )
        nearest = df_cgm.sort("time_diff").head(1)
        return nearest["value"].item()  # type: ignore[return-value]

    def _load_summary_data(self) -> LazyFrame[StravaSummarySchema]:
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
            pl.col("start_date_local").dt.strftime("%Y-%m-%d").alias("date"),
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

    def _aggregate_glucose(self, lf_right: LazyFrame[StravaSummarySchema]) -> LazyFrame[AggregatedGlucoseSchema]:
        return (
            self._load_glucose_data(lf_right)
            .group_by("activity_id")
            .agg(
                [
                    pl.col("value").first().alias("in_going_sg"),
                    pl.col("value").last().alias("out_going_sg"),
                    pl.col("value").mean().alias("avg_sg"),
                ]
            )
        )

    def _load_glucose_data(self, lf_right: LazyFrame[StravaSummarySchema]) -> LazyFrame[BaseGlucoseStreamSchema]:
        return (
            pl.scan_delta(str(self.data_paths.carelink))
            .filter(pl.col("type") == "CGM")
            .select(["value", "activity_id", "datetime"])
            .join(
                lf_right.select("activity_id", "start_date_local", "end_date_local", "run_type"),
                on="activity_id",
                how="inner",
            )
            .filter(
                (pl.col("datetime") >= pl.col("start_date_local") - pl.duration(minutes=5))
                & (pl.col("datetime") <= pl.col("end_date_local") + pl.duration(minutes=5))
            )
            .with_columns(pl.col("value").replace(0.0, None))
            .drop(["start_date_local", "end_date_local"])
        )

    def _aggregate_insulin_on_board(
        self, lf_right: LazyFrame[StravaSummarySchema]
    ) -> LazyFrame[AggregateInsulinOnBoard]:
        expression = (
            (
                pl.col("value")
                * (
                    1
                    - ((pl.col("start_date_local") - pl.col("datetime")).dt.total_seconds() / 60)
                    / PRE_RUN_INSULIN_MINUTES
                )
            )
            .clip(lower_bound=0.0)
            .alias("insulin_on_board_in_going")
        )
        return (
            self._load_pre_run_insulin_data(lf_right)
            .with_columns(expression)
            .group_by("activity_id")
            .agg(pl.sum("insulin_on_board_in_going"))
        )

    def _load_pre_run_insulin_data(self, lf_right: LazyFrame[StravaSummarySchema]) -> LazyFrame[PreRunInsulinSchema]:
        return (
            pl.scan_delta(str(self.data_paths.carelink))
            .filter(pl.col("type").is_in(["AUTO_BASAL_DELIVERY", "INSULIN"]))
            .select(["value", "activity_id", "datetime"])
            .join(
                lf_right.select("activity_id", "start_date_local", "end_date_local"),
                on="activity_id",
                how="inner",
            )
            .filter(
                (pl.col("datetime") >= pl.col("start_date_local") - pl.duration(minutes=PRE_RUN_INSULIN_MINUTES))
                & (pl.col("datetime") <= pl.col("start_date_local") + pl.duration(minutes=5))
            )
            .drop("end_date_local")
        )

    def _join_data(self, *, lf_left: LazyFrame[T], lf_right: LazyFrame[U]) -> LazyFrame[V]:
        return lf_left.join(
            lf_right,
            on="activity_id",
            how="left",
        )
