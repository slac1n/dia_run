import json
from datetime import datetime, timedelta
from typing import Any, TypeVar, cast

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
    BasalAdjustmentTirSchema,
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


def _typed(df: pl.DataFrame | pl.LazyFrame) -> Any:
    """Return *df* with a Pandera ``DataFrame[Schema]`` / ``LazyFrame[Schema]`` type.

    Pandera's generic wrappers are typing-only; at runtime a validated
    ``pl.DataFrame`` already *is* the correct value.  This one-liner
    centralises the ``Any`` escape-hatch so individual return sites stay
    free of ``# type: ignore`` comments.
    """
    return df


PRE_RUN_INSULIN_MINUTES = 180
EASY_KEYWORD = RunType.get_keyword(RunType.EASY) or ""
INTERVAL_KEYWORD = RunType.get_keyword(RunType.INTERVAL) or ""
TEMPO_KEYWORD = RunType.get_keyword(RunType.TEMPO) or ""
LONG_KEYWORD = RunType.get_keyword(RunType.LONG) or ""


class DataProcessor:
    def __init__(self, data_paths: DataPaths | None = None) -> None:
        self.data_paths = data_paths or DataPaths()
        self.df_summary: pl.DataFrame | None = None
        self.df_heartrate_streams: pl.DataFrame | None = None
        self.df_glucose_streams: pl.DataFrame | None = None
        self.df_pre_run_nutrition_summary: pl.DataFrame | None = None
        self.df_fueling_glucose_windows: pl.DataFrame | None = None
        self.df_fueling_impact: pl.DataFrame | None = None
        self.df_basal_adjustment_tir: pl.DataFrame | None = None
        self.df_cgm: pl.DataFrame | None = None
        self._cgm_by_activity: dict[int, pl.DataFrame] | None = None
        self._questionnaire_cache: dict[int, QuestionnaireModel] | None = None

    @check_types
    def get_summary(self) -> DataFrame[SummarySchema]:
        if self.df_summary is None:
            lf_summary = self._load_summary_data()
            lf_agg_glucose = self._aggregate_glucose(lf_summary)
            lf_agg_insulin_on_board = self._aggregate_insulin_on_board(lf_summary)
            lf_summary = self._join_data(lf_left=lf_summary, lf_right=lf_agg_glucose)
            lf_summary = self._join_data(lf_left=lf_summary, lf_right=lf_agg_insulin_on_board)
            self.df_summary = cast(pl.DataFrame, lf_summary.collect())

        return _typed(self.df_summary)

    def get_30_day_kpis(self, *, reference_date: datetime | None = None) -> KpiModel:
        df_summary = cast(pl.DataFrame, self.get_summary())
        reference = reference_date or datetime.now()
        cutoff = reference - timedelta(days=30)

        df_recent = df_summary.filter(pl.col("start_date_local") >= cutoff)

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

    def get_pending_questionnaire_count(self) -> int:
        df_summary = self.get_summary()
        questionnaire_ids = list(self._get_questionnaire_cache().keys())
        if questionnaire_ids:
            return len(df_summary.filter(~pl.col("activity_id").is_in(questionnaire_ids)))
        return len(df_summary)

    @check_types
    def get_specific_carelink(
        self, *, activity_id: int, start_datetime: datetime, end_datetime: datetime
    ) -> DataFrame[SpecificCarelinkSchema]:
        result = (
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
        return _typed(result)

    def get_questionnaire(self, activity_id: int) -> QuestionnaireModel:
        return self._get_questionnaire_cache().get(activity_id, QuestionnaireModel())

    @check_types
    def get_pre_run_nutrition_summary(self) -> DataFrame[PreRunNutritionSummarySchema]:
        if self.df_pre_run_nutrition_summary is not None:
            return _typed(self.df_pre_run_nutrition_summary)

        df_summary = cast(pl.DataFrame, self.get_summary())
        questionnaires = self._get_questionnaire_cache()
        nutrition_rows: list[dict[str, int | float | str]] = []

        for row in df_summary.iter_rows(named=True):
            activity_id: int = row["activity_id"]
            in_going_sg = row["in_going_sg"]
            name_date: str = row["name_date"]

            if in_going_sg is None:
                continue

            questionnaire = questionnaires.get(activity_id)
            if questionnaire is None:
                continue

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
            self.df_pre_run_nutrition_summary = pl.DataFrame(
                schema={
                    "activity_id": pl.Int64,
                    "total_carbohydrates_g": pl.Int64,
                    "earliest_time_before_start_min": pl.Int64,
                    "avg_bolus_percentage": pl.Float64,
                    "in_going_sg": pl.Float64,
                    "name_date": pl.Utf8,
                }
            )
            return _typed(self.df_pre_run_nutrition_summary)

        self.df_pre_run_nutrition_summary = pl.DataFrame(nutrition_rows)
        return _typed(self.df_pre_run_nutrition_summary)

    @check_types
    def get_heartrate_streams(self) -> DataFrame[HeartrateStreamsSchema]:
        if self.df_heartrate_streams is not None:
            return _typed(self.df_heartrate_streams)

        lf_summary = self._load_summary_data()
        self.df_heartrate_streams = (
            pl.scan_delta(str(self.data_paths.strava_stream))
            .select(["datetime", "heartrate", "activity_id"])
            .join(lf_summary.select(["activity_id", "run_type"]), on="activity_id", how="left")
            .select(pl.exclude("activity_id"))
        ).collect()
        return _typed(self.df_heartrate_streams)

    @check_types
    def get_glucose_streams(self) -> DataFrame[GlucoseStreamsSchema]:
        if self.df_glucose_streams is not None:
            return _typed(self.df_glucose_streams)

        lf_summary = self._load_summary_data()
        self.df_glucose_streams = self._load_glucose_data(lf_summary).drop("activity_id").collect()
        return _typed(self.df_glucose_streams)

    FUELING_WINDOW_MINUTES = 45
    PRE_INTAKE_WINDOW_MINUTES = 15

    @check_types
    def get_fueling_glucose_windows(self) -> DataFrame[FuelingGlucoseWindowSchema]:
        if self.df_fueling_glucose_windows is not None:
            return _typed(self.df_fueling_glucose_windows)

        df_summary = cast(pl.DataFrame, self.get_summary())
        questionnaires = self._get_questionnaire_cache()
        cgm_by_activity = self._get_cgm_by_activity()
        window_rows: list[dict[str, int | float | None]] = []

        for row in df_summary.iter_rows(named=True):
            activity_id: int = row["activity_id"]
            start_date_local: datetime = row["start_date_local"]
            end_date_local: datetime = row["end_date_local"]

            questionnaire = questionnaires.get(activity_id)
            if questionnaire is None:
                continue

            if not questionnaire.fueling_during_run:
                continue

            df_cgm = cgm_by_activity.get(activity_id)

            if df_cgm is None or df_cgm.is_empty():
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
            self.df_fueling_glucose_windows = pl.DataFrame(
                schema={
                    "activity_id": pl.Int64,
                    "fueling_index": pl.Int64,
                    "minutes_relative": pl.Float64,
                    "value": pl.Float64,
                }
            )
            return _typed(self.df_fueling_glucose_windows)

        self.df_fueling_glucose_windows = pl.DataFrame(window_rows)
        return _typed(self.df_fueling_glucose_windows)

    @check_types
    def get_fueling_impact(self) -> DataFrame[FuelingImpactSchema]:
        if self.df_fueling_impact is not None:
            return _typed(self.df_fueling_impact)

        df_summary = cast(pl.DataFrame, self.get_summary())
        df_windows = cast(pl.DataFrame, self.get_fueling_glucose_windows())
        questionnaires = self._get_questionnaire_cache()
        impact_rows: list[dict[str, object]] = []

        for row in df_summary.iter_rows(named=True):
            activity_id: int = row["activity_id"]
            start_date_local: datetime = row["start_date_local"]
            name_date: str = row["name_date"]

            questionnaire = questionnaires.get(activity_id)
            if questionnaire is None:
                continue

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
                peak_sg = float(df_valid.sort("value", descending=True)["value"].head(1).item())
                peak_increase = peak_sg - baseline_sg
                peak_row = df_valid.filter(pl.col("value") == peak_sg).sort("minutes_relative").head(1)
                time_to_peak_min = cast(float, peak_row["minutes_relative"].item())

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
            self.df_fueling_impact = pl.DataFrame(
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
            return _typed(self.df_fueling_impact)

        self.df_fueling_impact = pl.DataFrame(impact_rows).cast(
            {
                "baseline_sg": pl.Float64,
                "peak_sg": pl.Float64,
                "peak_increase": pl.Float64,
                "time_to_peak_min": pl.Float64,
            }
        )
        return _typed(self.df_fueling_impact)

    @check_types
    def get_basal_adjustment_tir(self) -> DataFrame[BasalAdjustmentTirSchema]:
        if self.df_basal_adjustment_tir is not None:
            return _typed(self.df_basal_adjustment_tir)

        df_summary = cast(pl.DataFrame, self.get_summary())
        questionnaires = self._get_questionnaire_cache()
        cgm_by_activity = self._get_cgm_by_activity()
        tir_rows: list[dict[str, object]] = []

        for row in df_summary.iter_rows(named=True):
            activity_id: int = row["activity_id"]
            start_date_local: datetime = row["start_date_local"]
            end_date_local: datetime = row["end_date_local"]
            name_date: str = row["name_date"]

            questionnaire = questionnaires.get(activity_id)
            if questionnaire is None:
                continue

            if not questionnaire.basal_adjustments:
                continue

            df_cgm = cgm_by_activity.get(activity_id)

            if df_cgm is None or df_cgm.is_empty():
                continue

            df_cgm = df_cgm.drop_nulls("value")

            adjustment_list = questionnaire.basal_adjustments
            for adjustment_index, adj in enumerate(adjustment_list):
                adjustment_start = start_date_local + timedelta(minutes=adj.start_time_min)
                adjustment_end = start_date_local + timedelta(minutes=adj.end_time_min)

                adjustment_start = max(adjustment_start, start_date_local)
                adjustment_end = min(adjustment_end, end_date_local)

                if adjustment_end <= adjustment_start:
                    continue

                duration_min = int((adjustment_end - adjustment_start).total_seconds() / 60)
                if duration_min <= 0:
                    continue

                df_interval = df_cgm.filter(
                    (pl.col("datetime") >= adjustment_start) & (pl.col("datetime") <= adjustment_end)
                )

                n_points = len(df_interval)
                if n_points == 0:
                    # Skip adjustments with no CGM coverage
                    continue

                points_in_range = len(
                    df_interval.filter(
                        (pl.col("value") >= TARGET_GLUCOSE_LOWER) & (pl.col("value") <= TARGET_GLUCOSE_UPPER)
                    )
                )

                tir_pct = round((points_in_range / n_points) * 100, 1) if n_points > 0 else 0.0
                covered_minutes = float(duration_min)

                tir_rows.append(
                    {
                        "activity_id": activity_id,
                        "adjustment_index": adjustment_index,
                        "type": adj.type,
                        "basal_rate_percentage": adj.basal_rate_percentage,
                        "duration_min": duration_min,
                        "tir_pct": tir_pct,
                        "n_points": n_points,
                        "covered_minutes": covered_minutes,
                        "name_date": name_date,
                    }
                )

        if not tir_rows:
            self.df_basal_adjustment_tir = pl.DataFrame(
                schema={
                    "activity_id": pl.Int64,
                    "adjustment_index": pl.Int64,
                    "type": pl.Utf8,
                    "basal_rate_percentage": pl.Float64,
                    "duration_min": pl.Int64,
                    "tir_pct": pl.Float64,
                    "n_points": pl.Int64,
                    "covered_minutes": pl.Float64,
                    "name_date": pl.Utf8,
                }
            )
            return _typed(self.df_basal_adjustment_tir)

        self.df_basal_adjustment_tir = pl.DataFrame(tir_rows).cast(
            {
                "basal_rate_percentage": pl.Float64,
                "tir_pct": pl.Float64,
                "covered_minutes": pl.Float64,
            }
        )
        return _typed(self.df_basal_adjustment_tir)

    def _get_baseline_glucose(self, *, activity_id: int, fueling_datetime: datetime) -> float | None:
        df_cgm = self._get_cgm_by_activity().get(activity_id)

        if df_cgm is None or df_cgm.is_empty():
            return None

        df_cgm = df_cgm.drop_nulls("value")

        if df_cgm.is_empty():
            return None

        df_cgm = df_cgm.with_columns(
            (pl.col("datetime") - fueling_datetime).dt.total_seconds().abs().alias("time_diff")
        )
        nearest = df_cgm.sort("time_diff").head(1)
        return float(nearest["value"].item())

    def _load_summary_data(self) -> LazyFrame[StravaSummarySchema]:
        return cast(
            LazyFrame[StravaSummarySchema],
            pl.scan_delta(str(self.data_paths.strava_summary)).with_columns(
                pl.format(
                    "{}:{}",
                    (pl.col("elapsed_time") // 3600),  # Hours
                    ((pl.col("elapsed_time") % 3600) // 60).cast(pl.Utf8).str.zfill(2),  # Minutes with zero-padding
                ).alias("human_readable_time"),
                pl.format(
                    "{}:{}",
                    (pl.col("average_pace").floor().cast(int)),  # Minutes
                    (((pl.col("average_pace") % 1) * 60).round(0).cast(int))
                    .cast(pl.Utf8)
                    .str.zfill(2),  # Seconds with zero-padding
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
                pl.when(pl.col("name").str.contains(EASY_KEYWORD))
                .then(pl.lit(RunType.EASY))
                .when(pl.col("name").str.contains(INTERVAL_KEYWORD))
                .then(pl.lit(RunType.INTERVAL))
                .when(pl.col("name").str.contains(TEMPO_KEYWORD))
                .then(pl.lit(RunType.TEMPO))
                .when(pl.col("name").str.contains(LONG_KEYWORD))
                .then(pl.lit(RunType.LONG))
                .when(pl.col("name").str.contains(RunType.get_race_pattern()))
                .then(pl.lit(RunType.RACE))
                .otherwise(pl.lit(RunType.OTHER))
                .alias("run_type"),
            ),
        )

    def _aggregate_glucose(self, lf_right: LazyFrame[StravaSummarySchema]) -> LazyFrame[AggregatedGlucoseSchema]:
        return cast(
            LazyFrame[AggregatedGlucoseSchema],
            (
                self._load_glucose_data(lf_right)
                .group_by("activity_id")
                .agg(
                    [
                        pl.col("value").first().alias("in_going_sg"),
                        pl.col("value").last().alias("out_going_sg"),
                        pl.col("value").mean().alias("avg_sg"),
                    ]
                )
            ),
        )

    def _load_glucose_data(self, lf_right: LazyFrame[StravaSummarySchema]) -> LazyFrame[BaseGlucoseStreamSchema]:
        return cast(
            LazyFrame[BaseGlucoseStreamSchema],
            (
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
            ),
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
        return cast(
            LazyFrame[AggregateInsulinOnBoard],
            (
                self._load_pre_run_insulin_data(lf_right)
                .with_columns(expression)
                .group_by("activity_id")
                .agg(pl.sum("insulin_on_board_in_going"))
            ),
        )

    def _load_pre_run_insulin_data(self, lf_right: LazyFrame[StravaSummarySchema]) -> LazyFrame[PreRunInsulinSchema]:
        return cast(
            LazyFrame[PreRunInsulinSchema],
            (
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
            ),
        )

    def _get_cgm_data(self) -> pl.DataFrame:
        if self.df_cgm is None:
            self.df_cgm = (
                pl.scan_delta(str(self.data_paths.carelink))
                .filter(pl.col("type") == "CGM")
                .select(["activity_id", "datetime", "value"])
                .with_columns(pl.col("value").replace(0.0, None))
                .sort(["activity_id", "datetime"])
                .collect()
            )
        return self.df_cgm

    def _get_cgm_by_activity(self) -> dict[int, pl.DataFrame]:
        if self._cgm_by_activity is None:
            self._cgm_by_activity = {}
            for group in self._get_cgm_data().partition_by("activity_id", maintain_order=True):
                activity_id = int(group["activity_id"].item(0))
                self._cgm_by_activity[activity_id] = group.select(["datetime", "value"])
        return self._cgm_by_activity

    def _get_questionnaire_cache(self) -> dict[int, QuestionnaireModel]:
        if self._questionnaire_cache is None:
            self.data_paths.questionnaire.mkdir(parents=True, exist_ok=True)
            self._questionnaire_cache = {}
            for questionnaire_path in self.data_paths.questionnaire.glob("*.json"):
                if not questionnaire_path.stem.isdigit():
                    continue

                with open(questionnaire_path) as f:
                    data = json.load(f)

                self._questionnaire_cache[int(questionnaire_path.stem)] = QuestionnaireModel.model_validate(data)

        return self._questionnaire_cache

    def _join_data(self, *, lf_left: LazyFrame[T], lf_right: LazyFrame[U]) -> LazyFrame[V]:
        return _typed(
            lf_left.join(
                lf_right,
                on="activity_id",
                how="left",
            )
        )
