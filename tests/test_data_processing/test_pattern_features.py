from datetime import datetime, timedelta
from pathlib import Path

import plotly.graph_objects as go
import polars as pl
import pytest

from dia_run.dashboard.charts.basal_adjustment_impact import create_basal_lead_time_effect_chart
from dia_run.dashboard.charts.pattern_insights import (
    create_first20_stability_effect_chart,
    create_sg20_predictor_chart,
    create_similar_runs_benchmark_chart,
    create_time_of_day_outcomes_chart,
)
from dia_run.data_models.paths import DataPaths
from dia_run.data_models.questionnaire import BasalAdjustment, QuestionnaireModel
from dia_run.data_models.schemas import PatternAggregateSchema
from dia_run.data_processing.data_processing import (
    DataProcessor,
    _compute_basal_lead_time,
    _compute_duration_band,
    _compute_glucose_band,
)


class TestActivityOutcomes:
    def test_outcomes_contains_all_activities(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        df = processor._get_activity_outcomes()  # noqa: SLF001
        assert set(df["activity_id"].to_list()) == {1001, 1002, 1003, 1004}
        assert {"tir_pct", "good_finish_flag", "low_event_flag", "run_variability_p90_p10"} <= set(df.columns)

    def test_outcomes_is_cached(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        first = processor._get_activity_outcomes()  # noqa: SLF001
        second = processor._get_activity_outcomes()  # noqa: SLF001
        assert first is second


class TestTimeOfDayBuckets:
    def test_bucket_assignment(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        df = processor._get_time_of_day_buckets()  # noqa: SLF001
        buckets = dict(zip(df["activity_id"].to_list(), df["time_of_day_bucket"].to_list(), strict=True))
        assert buckets[1001] == "morning"  # 10:00
        assert buckets[1002] == "evening"  # 18:00
        assert buckets[1003] is None  # 14:00 — off window (12-15)
        assert buckets[1004] == "morning"  # 08:00

    def test_off_window_excluded_from_outcomes(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        outcomes = processor.get_time_of_day_outcomes()
        # Activity 1003 is off-window so the aggregation should only cover 1001/1002/1004
        assert outcomes["n"].sum() == 3


class TestStable20Flags:
    def test_flags_cover_all_activities(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        df = processor._get_stable_20_flags()  # noqa: SLF001
        assert set(df["activity_id"].to_list()) == {1001, 1002, 1003, 1004}
        assert df.schema["stable_20_flag"] == pl.Boolean

    def test_is_cached(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        first = processor._get_stable_20_flags()  # noqa: SLF001
        second = processor._get_stable_20_flags()  # noqa: SLF001
        assert first is second


class TestSg20Bins:
    def test_bins_values(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        df = processor._get_sg_20_bins()  # noqa: SLF001
        assert set(df["activity_id"].to_list()) == {1001, 1002, 1003, 1004}
        bins = set(df["sg_20_bin"].drop_nulls().to_list())
        assert bins <= {"<100", "100-129", "130-159", "160-180", ">180"}

    def test_is_cached(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        first = processor._get_sg_20_bins()  # noqa: SLF001
        second = processor._get_sg_20_bins()  # noqa: SLF001
        assert first is second


class TestBasalLeadTimeBuckets:
    def test_buckets_from_fixture(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        df = processor._get_basal_lead_time_buckets()  # noqa: SLF001
        buckets = dict(zip(df["activity_id"].to_list(), df["basal_lead_time_bucket"].to_list(), strict=True))
        assert buckets[1001] == "none"  # no questionnaire adjustments
        assert buckets[1002] == "0-30"  # lead_time=10 → "0-30"
        assert buckets[1003] == "none"  # no adjustments
        assert buckets[1004] == "0-30"  # lead_time=30 → "0-30"


class TestDurationBand:
    @pytest.mark.parametrize(
        ("moving_time_sec", "expected"),
        [
            (45 * 60, "<=45"),
            (46 * 60, "46-75"),
            (75 * 60, "46-75"),
            (76 * 60, "76-120"),
            (120 * 60, "76-120"),
            (121 * 60, ">120"),
        ],
    )
    def test_boundaries(self, *, moving_time_sec: int, expected: str) -> None:
        assert _compute_duration_band(moving_time_sec) == expected


class TestGlucoseBand:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, None),
            (80.0, "<100"),
            (99.9, "<100"),
            (100.0, "100-129"),
            (129.0, "100-129"),
            (130.0, "130-159"),
            (159.0, "130-159"),
            (160.0, "160-180"),
            (180.0, "160-180"),
            (181.0, ">180"),
        ],
    )
    def test_bands(self, *, value: float | None, expected: str | None) -> None:
        assert _compute_glucose_band(value) == expected


class TestBasalLeadTime:
    def test_no_questionnaire_returns_none_bucket(self) -> None:
        lead_time, bucket = _compute_basal_lead_time(None)
        assert lead_time is None
        assert bucket == "none"

    def test_no_adjustments_returns_none_bucket(self) -> None:
        questionnaire = QuestionnaireModel(basal_adjustments=[])
        lead_time, bucket = _compute_basal_lead_time(questionnaire)
        assert lead_time is None
        assert bucket == "none"

    def test_only_post_start_adjustments_returns_none(self) -> None:
        questionnaire = QuestionnaireModel(
            basal_adjustments=[
                BasalAdjustment(type="temp_basal", start_time_min=0, end_time_min=30, basal_rate_percentage=80.0)
            ]
        )
        lead_time, bucket = _compute_basal_lead_time(questionnaire)
        assert lead_time is None
        assert bucket == "none"

    def test_uses_most_negative_start_time(self) -> None:
        questionnaire = QuestionnaireModel(
            basal_adjustments=[
                BasalAdjustment(type="temp_basal", start_time_min=-10, end_time_min=20, basal_rate_percentage=80.0),
                BasalAdjustment(type="temp_basal", start_time_min=-45, end_time_min=-15, basal_rate_percentage=70.0),
            ]
        )
        lead_time, bucket = _compute_basal_lead_time(questionnaire)
        assert lead_time == 45
        assert bucket == "31-60"

    @pytest.mark.parametrize(
        ("start_time_min", "expected_bucket"),
        [
            (-1, "0-30"),
            (-30, "0-30"),
            (-31, "31-60"),
            (-60, "31-60"),
            (-61, "61-90"),
            (-90, "61-90"),
            (-91, ">90"),
            (-120, ">90"),
        ],
    )
    def test_bucket_boundaries(self, *, start_time_min: int, expected_bucket: str) -> None:
        questionnaire = QuestionnaireModel(
            basal_adjustments=[
                BasalAdjustment(
                    type="temp_basal", start_time_min=start_time_min, end_time_min=0, basal_rate_percentage=80.0
                )
            ]
        )
        _, bucket = _compute_basal_lead_time(questionnaire)
        assert bucket == expected_bucket


class TestNearestCgmValue:
    def _make_df(self, *, offsets_minutes: list[float], values: list[float]) -> pl.DataFrame:
        base = datetime(2026, 4, 17, 10, 0, 0)
        return pl.DataFrame(
            {
                "datetime": [base + timedelta(minutes=m) for m in offsets_minutes],
                "value": values,
            }
        )

    def test_returns_nearest_within_tolerance(self) -> None:
        processor = DataProcessor(
            DataPaths(
                carelink=Path("/tmp/nope"),
                strava_summary=Path("/tmp/nope"),
                strava_stream=Path("/tmp/nope"),
                questionnaire=Path("/tmp/nope"),
            )
        )
        df = self._make_df(offsets_minutes=[0, 5, 17, 30], values=[110.0, 115.0, 125.0, 150.0])
        target = datetime(2026, 4, 17, 10, 20, 0)
        result = processor._nearest_cgm_value(df, target_dt=target, tolerance_min=7.5)
        assert result == 125.0

    def test_returns_none_when_outside_tolerance(self) -> None:
        processor = DataProcessor(
            DataPaths(
                carelink=Path("/tmp/nope"),
                strava_summary=Path("/tmp/nope"),
                strava_stream=Path("/tmp/nope"),
                questionnaire=Path("/tmp/nope"),
            )
        )
        df = self._make_df(offsets_minutes=[0, 30], values=[110.0, 150.0])
        target = datetime(2026, 4, 17, 10, 20, 0)
        result = processor._nearest_cgm_value(df, target_dt=target, tolerance_min=7.5)
        assert result is None

    def test_returns_none_for_empty_df(self) -> None:
        processor = DataProcessor(
            DataPaths(
                carelink=Path("/tmp/nope"),
                strava_summary=Path("/tmp/nope"),
                strava_stream=Path("/tmp/nope"),
                questionnaire=Path("/tmp/nope"),
            )
        )
        result = processor._nearest_cgm_value(None, target_dt=datetime.now(), tolerance_min=7.5)
        assert result is None


class TestAggregators:
    def test_time_of_day_outcomes(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        result = processor.get_time_of_day_outcomes()

        PatternAggregateSchema.validate(result)
        assert set(result["bucket_dim"].unique().to_list()) == {"time_of_day"}
        assert set(result["bucket_key"].to_list()) <= {"morning", "evening"}
        assert (result["actionable"] == (result["n"] >= 8)).all()

    def test_first20_stability_effect_drops_null_flags(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        result = processor.get_first20_stability_effect()

        PatternAggregateSchema.validate(result)
        assert set(result["bucket_dim"].unique().to_list()) <= {"stability"}
        assert set(result["bucket_key"].to_list()) <= {"true", "false"}

    def test_basal_lead_time_effect(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        result = processor.get_basal_lead_time_effect()

        PatternAggregateSchema.validate(result)
        assert set(result["bucket_dim"].unique().to_list()) <= {"basal_lead_time"}
        allowed = {"none", "0-30", "31-60", "61-90", ">90"}
        assert set(result["bucket_key"].to_list()) <= allowed

    def test_sg20_predictor_drops_null_bins(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        result = processor.get_sg20_predictor()

        PatternAggregateSchema.validate(result)
        allowed = {"<100", "100-129", "130-159", "160-180", ">180"}
        assert set(result["bucket_key"].to_list()) <= allowed

    def test_similar_runs_cohorts_join_key(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        result = processor.get_similar_runs_cohorts()

        PatternAggregateSchema.validate(result)
        for key in result["bucket_key"].to_list():
            assert key.count("|") == 2


class TestPatternInsightChartsSmoke:
    @pytest.mark.parametrize(
        "builder",
        [
            create_time_of_day_outcomes_chart,
            create_first20_stability_effect_chart,
            create_basal_lead_time_effect_chart,
            create_sg20_predictor_chart,
            create_similar_runs_benchmark_chart,
        ],
    )
    def test_builders_return_figure(self, *, test_data_paths: DataPaths, builder) -> None:  # type: ignore[no-untyped-def]
        processor = DataProcessor(test_data_paths)
        fig = builder(data_processor=processor)
        assert isinstance(fig, go.Figure)
