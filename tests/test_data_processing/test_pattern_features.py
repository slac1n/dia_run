from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from dia_run.data_models.paths import DataPaths
from dia_run.data_models.questionnaire import BasalAdjustment, QuestionnaireModel
from dia_run.data_models.schemas import PatternAggregateSchema, PatternFeaturesSchema
from dia_run.data_processing.data_processing import (
    DataProcessor,
    _compute_basal_lead_time,
    _compute_duration_band,
    _compute_glucose_band,
)


class TestPatternFeaturesBuild:
    def test_get_pattern_features_validates(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        df = processor.get_pattern_features()

        PatternFeaturesSchema.validate(df)
        assert len(df) == 4
        assert set(df["activity_id"].to_list()) == {1001, 1002, 1003, 1004}

    def test_pattern_features_is_cached(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        first = processor.get_pattern_features()
        second = processor.get_pattern_features()
        assert first.equals(second)


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
            (-1, "0-15"),
            (-15, "0-15"),
            (-16, "16-30"),
            (-30, "16-30"),
            (-31, "31-60"),
            (-60, "31-60"),
            (-61, ">60"),
            (-120, ">60"),
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
        assert set(result["bucket_key"].to_list()) <= {"before_noon", "after_noon"}

        features = processor.get_pattern_features()
        assert result["n"].sum() == len(features)
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
        allowed = {"none", "0-15", "16-30", "31-60", ">60"}
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
