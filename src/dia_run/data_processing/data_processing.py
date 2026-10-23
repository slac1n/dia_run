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
    FuelingTimingAggregateSchema,
    GlucoseStreamsSchema,
    HeartrateStreamsSchema,
    PatternAggregateSchema,
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

SG_TOLERANCE_MINUTES: float = 7.5
EARLY_WINDOW_MINUTES: int = 20
STABLE_DELTA_LIMIT: int = 20


def _compute_duration_band(moving_time_sec: int) -> str:
    if moving_time_sec <= 45 * 60:
        return "<=45"
    if moving_time_sec <= 75 * 60:
        return "46-75"
    if moving_time_sec <= 120 * 60:
        return "76-120"
    return ">120"


def _compute_glucose_band(value: float | None) -> str | None:
    if value is None:
        return None
    if value < 100:
        return "<100"
    if value <= 129:
        return "100-129"
    if value <= 159:
        return "130-159"
    if value <= 180:
        return "160-180"
    return ">180"


def _compute_fueling_timing_bucket(time_during_run_min: int) -> str:
    if time_during_run_min <= 15:
        return "0-15"
    if time_during_run_min <= 30:
        return "16-30"
    if time_during_run_min <= 60:
        return "31-60"
    if time_during_run_min <= 90:
        return "61-90"
    return ">90"


def _compute_basal_lead_time(questionnaire: QuestionnaireModel | None) -> tuple[int | None, str]:
    if questionnaire is None or not questionnaire.basal_adjustments:
        return None, "none"
    pre_run_starts = [adj.start_time_min for adj in questionnaire.basal_adjustments if adj.start_time_min < 0]
    if not pre_run_starts:
        return None, "none"
    lead_time = -min(pre_run_starts)
    if lead_time <= 30:
        return lead_time, "0-30"
    if lead_time <= 60:
        return lead_time, "31-60"
    if lead_time <= 90:
        return lead_time, "61-90"
    return lead_time, ">90"


_PATTERN_AGGREGATE_SCHEMA: dict[str, pl.DataType] = {
    "bucket_key": pl.Utf8,
    "bucket_dim": pl.Utf8,
    "n": pl.Int64,
    "tir_median": pl.Float64,
    "tir_mean": pl.Float64,
    "low_event_rate": pl.Float64,
    "good_finish_rate": pl.Float64,
    "stable_20_rate": pl.Float64,
    "variability_median": pl.Float64,
    "actionable": pl.Boolean,
}

_FUELING_AGGREGATE_SCHEMA: dict[str, pl.DataType] = {
    "bucket_key": pl.Utf8,
    "bucket_dim": pl.Utf8,
    "n": pl.Int64,
    "post_tir_rate": pl.Float64,
    "avoided_low_rate": pl.Float64,
    "peak_no_spike_rate": pl.Float64,
    "actionable": pl.Boolean,
}


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
        self._activity_outcomes: pl.DataFrame | None = None
        self._stable_20_flags: pl.DataFrame | None = None
        self._sg_20_bins: pl.DataFrame | None = None
        self._fueling_event_metrics: pl.DataFrame | None = None

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

    def _compute_fueling_event_metrics(self) -> pl.DataFrame:
        if self._fueling_event_metrics is not None:
            return self._fueling_event_metrics

        df_impact = cast(pl.DataFrame, self.get_fueling_impact())
        df_windows = cast(pl.DataFrame, self.get_fueling_glucose_windows())
        questionnaires = self._get_questionnaire_cache()

        metric_rows: list[dict[str, Any]] = []
        for row in df_impact.iter_rows(named=True):
            activity_id: int = row["activity_id"]
            fueling_index: int = row["fueling_index"]
            baseline_sg: float | None = row["baseline_sg"]
            peak_sg: float | None = row["peak_sg"]

            questionnaire = questionnaires.get(activity_id)
            if questionnaire is None or fueling_index >= len(questionnaire.fueling_during_run):
                continue
            time_during_run_min = questionnaire.fueling_during_run[fueling_index].time_during_run_min

            post_window = df_windows.filter(
                (pl.col("activity_id") == activity_id)
                & (pl.col("fueling_index") == fueling_index)
                & (pl.col("minutes_relative") >= 0)
                & (pl.col("minutes_relative") <= self.FUELING_WINDOW_MINUTES)
            ).drop_nulls("value")

            if post_window.is_empty():
                post_tir_rate: float | None = None
                avoided_low: bool | None = None
            else:
                post_values = post_window["value"]
                post_tir_rate = float(
                    post_values.is_between(TARGET_GLUCOSE_LOWER, TARGET_GLUCOSE_UPPER).mean()  # type: ignore[arg-type]
                )
                avoided_low = bool((post_values >= TARGET_GLUCOSE_LOWER).all())

            peak_no_spike: bool | None = peak_sg <= TARGET_GLUCOSE_UPPER if peak_sg is not None else None

            metric_rows.append(
                {
                    "activity_id": activity_id,
                    "fueling_index": fueling_index,
                    "time_into_run_bucket": _compute_fueling_timing_bucket(time_during_run_min),
                    "sg_at_fueling_band": _compute_glucose_band(baseline_sg),
                    "post_tir_rate": post_tir_rate,
                    "avoided_low": avoided_low,
                    "peak_no_spike": peak_no_spike,
                }
            )

        self._fueling_event_metrics = pl.DataFrame(
            metric_rows or [],
            schema={
                "activity_id": pl.Int64,
                "fueling_index": pl.Int64,
                "time_into_run_bucket": pl.Utf8,
                "sg_at_fueling_band": pl.Utf8,
                "post_tir_rate": pl.Float64,
                "avoided_low": pl.Boolean,
                "peak_no_spike": pl.Boolean,
            },
        )
        return self._fueling_event_metrics

    @check_types
    def get_fueling_timing_effect(self) -> DataFrame[FuelingTimingAggregateSchema]:
        df = self._compute_fueling_event_metrics().filter(pl.col("time_into_run_bucket").is_not_null())
        return _typed(self._build_fueling_aggregate(df=df, group_key="time_into_run_bucket", bucket_dim="fueling_time"))

    @check_types
    def get_fueling_sg_effect(self) -> DataFrame[FuelingTimingAggregateSchema]:
        df = self._compute_fueling_event_metrics().filter(pl.col("sg_at_fueling_band").is_not_null())
        return _typed(self._build_fueling_aggregate(df=df, group_key="sg_at_fueling_band", bucket_dim="fueling_sg"))

    def _build_fueling_aggregate(self, *, df: pl.DataFrame, group_key: str, bucket_dim: str) -> pl.DataFrame:
        if df.is_empty():
            return pl.DataFrame(schema=_FUELING_AGGREGATE_SCHEMA)

        grouped = (
            df.group_by(group_key, maintain_order=True)
            .agg(
                pl.len().cast(pl.Int64).alias("n"),
                pl.col("post_tir_rate").mean().cast(pl.Float64).alias("post_tir_rate"),
                pl.col("avoided_low").cast(pl.Float64).mean().alias("avoided_low_rate"),
                pl.col("peak_no_spike").cast(pl.Float64).mean().alias("peak_no_spike_rate"),
            )
            .with_columns(pl.col(group_key).cast(pl.Utf8))
            .rename({group_key: "bucket_key"})
            .with_columns(
                pl.lit(bucket_dim).alias("bucket_dim"),
                (pl.col("n") >= 8).alias("actionable"),
            )
            .select(list(_FUELING_AGGREGATE_SCHEMA.keys()))
        )
        return grouped

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

    def _get_activity_outcomes(self) -> pl.DataFrame:
        if self._activity_outcomes is not None:
            return self._activity_outcomes

        lf_summary = self._load_summary_data()
        lf_cgm_metrics = (
            self._load_glucose_data(lf_summary)
            .drop_nulls("value")
            .group_by("activity_id")
            .agg(
                (pl.col("value").is_between(TARGET_GLUCOSE_LOWER, TARGET_GLUCOSE_UPPER).mean() * 100)
                .round(1)
                .cast(pl.Float64)
                .alias("tir_pct"),
                (pl.col("value") < TARGET_GLUCOSE_LOWER).any().alias("low_event_flag"),
                (pl.col("value").quantile(0.9) - pl.col("value").quantile(0.1))
                .round(1)
                .cast(pl.Float64)
                .alias("run_variability_p90_p10"),
            )
        )

        df_summary = cast(pl.DataFrame, self.get_summary())
        self._activity_outcomes = (
            df_summary.lazy()
            .select("activity_id", "out_going_sg")
            .join(lf_cgm_metrics, on="activity_id", how="left")
            .with_columns(
                pl.col("out_going_sg").is_between(TARGET_GLUCOSE_LOWER, TARGET_GLUCOSE_UPPER).alias("good_finish_flag")
            )
            .select(
                "activity_id",
                "tir_pct",
                "good_finish_flag",
                "low_event_flag",
                "run_variability_p90_p10",
            )
            .collect()
        )
        return self._activity_outcomes

    def _get_time_of_day_buckets(self) -> pl.DataFrame:
        df_summary = cast(pl.DataFrame, self.get_summary())
        hour = pl.col("start_date_local").dt.hour()
        return df_summary.select(
            "activity_id",
            pl.when(hour.is_between(5, 11))
            .then(pl.lit("morning"))
            .when(hour.is_between(15, 21))
            .then(pl.lit("evening"))
            .otherwise(pl.lit(None, dtype=pl.Utf8))
            .alias("time_of_day_bucket"),
        )

    def _get_stable_20_flags(self) -> pl.DataFrame:
        if self._stable_20_flags is not None:
            return self._stable_20_flags

        df_summary = cast(pl.DataFrame, self.get_summary())
        cgm_by_activity = self._get_cgm_by_activity()
        rows: list[dict[str, Any]] = []
        for row in df_summary.iter_rows(named=True):
            activity_id = int(row["activity_id"])
            start_dt: datetime = row["start_date_local"]
            df_cgm = cgm_by_activity.get(activity_id)

            sg_start = self._nearest_cgm_value(df_cgm, target_dt=start_dt, tolerance_min=SG_TOLERANCE_MINUTES)
            sg_20 = self._nearest_cgm_value(
                df_cgm,
                target_dt=start_dt + timedelta(minutes=EARLY_WINDOW_MINUTES),
                tolerance_min=SG_TOLERANCE_MINUTES,
            )

            stable_flag: bool | None = None
            if df_cgm is not None and sg_start is not None and sg_20 is not None:
                df_early = df_cgm.drop_nulls("value").filter(
                    (pl.col("datetime") >= start_dt)
                    & (pl.col("datetime") <= start_dt + timedelta(minutes=EARLY_WINDOW_MINUTES))
                )
                if not df_early.is_empty():
                    early_values = df_early["value"]
                    early_in_range = bool(
                        (early_values >= TARGET_GLUCOSE_LOWER).all() and (early_values <= TARGET_GLUCOSE_UPPER).all()
                    )
                    stable_flag = bool(early_in_range and abs(sg_20 - sg_start) <= STABLE_DELTA_LIMIT)

            rows.append({"activity_id": activity_id, "stable_20_flag": stable_flag})

        self._stable_20_flags = pl.DataFrame(
            rows or [],
            schema={"activity_id": pl.Int64, "stable_20_flag": pl.Boolean},
        )
        return self._stable_20_flags

    def _get_sg_20_bins(self) -> pl.DataFrame:
        if self._sg_20_bins is not None:
            return self._sg_20_bins

        df_summary = cast(pl.DataFrame, self.get_summary())
        cgm_by_activity = self._get_cgm_by_activity()
        rows: list[dict[str, Any]] = []
        for row in df_summary.iter_rows(named=True):
            activity_id = int(row["activity_id"])
            start_dt: datetime = row["start_date_local"]
            sg_20 = self._nearest_cgm_value(
                cgm_by_activity.get(activity_id),
                target_dt=start_dt + timedelta(minutes=EARLY_WINDOW_MINUTES),
                tolerance_min=SG_TOLERANCE_MINUTES,
            )
            rows.append({"activity_id": activity_id, "sg_20_bin": _compute_glucose_band(sg_20)})

        self._sg_20_bins = pl.DataFrame(
            rows or [],
            schema={"activity_id": pl.Int64, "sg_20_bin": pl.Utf8},
        )
        return self._sg_20_bins

    def _get_basal_lead_time_buckets(self) -> pl.DataFrame:
        df_summary = cast(pl.DataFrame, self.get_summary())
        questionnaires = self._get_questionnaire_cache()
        rows: list[dict[str, str | int]] = [
            {
                "activity_id": int(row["activity_id"]),
                "basal_lead_time_bucket": _compute_basal_lead_time(questionnaires.get(int(row["activity_id"])))[1],
            }
            for row in df_summary.iter_rows(named=True)
        ]
        return pl.DataFrame(
            rows or [],
            schema={"activity_id": pl.Int64, "basal_lead_time_bucket": pl.Utf8},
        )

    def _get_duration_and_start_bands(self) -> pl.DataFrame:
        df_summary = cast(pl.DataFrame, self.get_summary())
        return df_summary.select(
            "activity_id",
            "run_type",
            pl.when(pl.col("moving_time") <= 45 * 60)
            .then(pl.lit("<=45"))
            .when(pl.col("moving_time") <= 75 * 60)
            .then(pl.lit("46-75"))
            .when(pl.col("moving_time") <= 120 * 60)
            .then(pl.lit("76-120"))
            .otherwise(pl.lit(">120"))
            .alias("duration_band"),
            pl.when(pl.col("in_going_sg").is_null())
            .then(pl.lit(None, dtype=pl.Utf8))
            .when(pl.col("in_going_sg") < 100)
            .then(pl.lit("<100"))
            .when(pl.col("in_going_sg") <= 129)
            .then(pl.lit("100-129"))
            .when(pl.col("in_going_sg") <= 159)
            .then(pl.lit("130-159"))
            .when(pl.col("in_going_sg") <= 180)
            .then(pl.lit("160-180"))
            .otherwise(pl.lit(">180"))
            .alias("start_glucose_band"),
        )

    @check_types
    def get_time_of_day_outcomes(self) -> DataFrame[PatternAggregateSchema]:
        df = (
            self._get_activity_outcomes()
            .join(self._get_time_of_day_buckets(), on="activity_id", how="inner")
            .filter(pl.col("time_of_day_bucket").is_not_null())
        )
        return _typed(self._build_pattern_aggregate(df=df, group_keys=["time_of_day_bucket"], bucket_dim="time_of_day"))

    @check_types
    def get_first20_stability_effect(self) -> DataFrame[PatternAggregateSchema]:
        df = (
            self._get_activity_outcomes()
            .join(self._get_stable_20_flags(), on="activity_id", how="inner")
            .filter(pl.col("stable_20_flag").is_not_null())
        )
        return _typed(self._build_pattern_aggregate(df=df, group_keys=["stable_20_flag"], bucket_dim="stability"))

    @check_types
    def get_basal_lead_time_effect(self) -> DataFrame[PatternAggregateSchema]:
        df = (
            self._get_activity_outcomes()
            .join(self._get_basal_lead_time_buckets(), on="activity_id", how="inner")
            .join(self._get_stable_20_flags(), on="activity_id", how="left")
        )
        return _typed(
            self._build_pattern_aggregate(df=df, group_keys=["basal_lead_time_bucket"], bucket_dim="basal_lead_time")
        )

    @check_types
    def get_sg20_predictor(self) -> DataFrame[PatternAggregateSchema]:
        df = (
            self._get_activity_outcomes()
            .join(self._get_sg_20_bins(), on="activity_id", how="inner")
            .filter(pl.col("sg_20_bin").is_not_null())
        )
        return _typed(self._build_pattern_aggregate(df=df, group_keys=["sg_20_bin"], bucket_dim="sg20"))

    @check_types
    def get_similar_runs_cohorts(self) -> DataFrame[PatternAggregateSchema]:
        df = (
            self._get_activity_outcomes()
            .join(self._get_duration_and_start_bands(), on="activity_id", how="inner")
            .filter(
                pl.col("run_type").is_not_null()
                & pl.col("duration_band").is_not_null()
                & pl.col("start_glucose_band").is_not_null()
            )
        )
        return _typed(
            self._build_pattern_aggregate(
                df=df,
                group_keys=["run_type", "duration_band", "start_glucose_band"],
                bucket_dim="cohort",
            )
        )

    def _build_pattern_aggregate(self, *, df: pl.DataFrame, group_keys: list[str], bucket_dim: str) -> pl.DataFrame:
        if df.is_empty():
            return pl.DataFrame(schema=_PATTERN_AGGREGATE_SCHEMA)

        has_stable = "stable_20_flag" in df.columns
        agg_exprs: list[pl.Expr] = [
            pl.len().cast(pl.Int64).alias("n"),
            pl.col("tir_pct").median().cast(pl.Float64).alias("tir_median"),
            pl.col("tir_pct").mean().cast(pl.Float64).alias("tir_mean"),
            pl.col("low_event_flag").cast(pl.Float64).mean().alias("low_event_rate"),
            pl.col("good_finish_flag").cast(pl.Float64).mean().alias("good_finish_rate"),
            pl.col("run_variability_p90_p10").median().cast(pl.Float64).alias("variability_median"),
        ]
        if has_stable:
            agg_exprs.append(pl.col("stable_20_flag").cast(pl.Float64).mean().alias("stable_20_rate"))

        grouped = (
            df.group_by(group_keys, maintain_order=True)
            .agg(agg_exprs)
            .with_columns([pl.col(key).cast(pl.Utf8) for key in group_keys])
        )
        if not has_stable:
            grouped = grouped.with_columns(pl.lit(None, dtype=pl.Float64).alias("stable_20_rate"))

        if len(group_keys) == 1:
            grouped = grouped.rename({group_keys[0]: "bucket_key"})
        else:
            grouped = grouped.with_columns(
                pl.concat_str([pl.col(key) for key in group_keys], separator="|").alias("bucket_key")
            ).drop(group_keys)

        return grouped.with_columns(
            pl.lit(bucket_dim).alias("bucket_dim"),
            (pl.col("n") >= 8).alias("actionable"),
        ).select(list(_PATTERN_AGGREGATE_SCHEMA.keys()))

    def _nearest_cgm_value(
        self, df_cgm: pl.DataFrame | None, *, target_dt: datetime, tolerance_min: float
    ) -> float | None:
        if df_cgm is None or df_cgm.is_empty():
            return None
        df_valid = df_cgm.drop_nulls("value")
        if df_valid.is_empty():
            return None
        df_valid = df_valid.with_columns(
            (pl.col("datetime") - target_dt).dt.total_seconds().abs().alias("_time_diff_sec")
        )
        nearest = df_valid.sort("_time_diff_sec").head(1)
        time_diff_sec = float(nearest["_time_diff_sec"].item())
        if time_diff_sec / 60.0 > tolerance_min:
            return None
        return float(nearest["value"].item())

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
                        (pl.col("value").is_between(TARGET_GLUCOSE_LOWER, TARGET_GLUCOSE_UPPER).mean() * 100)
                        .round(1)
                        .alias("tir_pct"),
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
