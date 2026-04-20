import polars as pl
import pytest

from dia_run.data_models.paths import DataPaths
from dia_run.data_models.schemas import FUELING_TIMING_BUCKETS, GLUCOSE_BANDS, FuelingTimingAggregateSchema
from dia_run.data_processing.data_processing import DataProcessor, _compute_fueling_timing_bucket


class TestFuelingTimingBucket:
    @pytest.mark.parametrize(
        ("minutes", "expected"),
        [
            (0, "0-15"),
            (15, "0-15"),
            (16, "16-30"),
            (30, "16-30"),
            (31, "31-60"),
            (60, "31-60"),
            (61, "61-90"),
            (90, "61-90"),
            (91, ">90"),
            (120, ">90"),
        ],
    )
    def test_boundaries(self, *, minutes: int, expected: str) -> None:
        assert _compute_fueling_timing_bucket(minutes) == expected


class TestFuelingEventMetrics:
    def test_metrics_produced_per_fueling_event(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        df = processor._compute_fueling_event_metrics()  # noqa: SLF001

        # Activity 1002: 1 fueling; activity 1003: 2 fuelings; activity 1004: 2 fuelings = 5 events
        assert len(df) == 5
        assert {"activity_id", "fueling_index", "time_into_run_bucket", "sg_at_fueling_band"} <= set(df.columns)
        assert {"post_tir_rate", "avoided_low", "peak_in_range"} <= set(df.columns)

    def test_time_into_run_buckets_are_in_canonical_set(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        df = processor._compute_fueling_event_metrics()  # noqa: SLF001
        assert set(df["time_into_run_bucket"].drop_nulls().to_list()) <= set(FUELING_TIMING_BUCKETS)

    def test_sg_at_fueling_bands_are_in_canonical_set(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        df = processor._compute_fueling_event_metrics()  # noqa: SLF001
        assert set(df["sg_at_fueling_band"].drop_nulls().to_list()) <= set(GLUCOSE_BANDS)

    def test_peak_in_range_follows_peak_sg(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        metrics = processor._compute_fueling_event_metrics()  # noqa: SLF001
        impact = processor.get_fueling_impact()
        merged = metrics.join(impact, on=["activity_id", "fueling_index"], how="inner")
        for row in merged.iter_rows(named=True):
            if row["peak_sg"] is None:
                assert row["peak_in_range"] is None
            else:
                assert row["peak_in_range"] == (row["peak_sg"] <= 180)

    def test_avoided_low_consistent_with_post_window_values(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        metrics = processor._compute_fueling_event_metrics()  # noqa: SLF001
        windows = processor.get_fueling_glucose_windows()

        for row in metrics.iter_rows(named=True):
            if row["avoided_low"] is None:
                continue
            post = windows.filter(
                (pl.col("activity_id") == row["activity_id"])
                & (pl.col("fueling_index") == row["fueling_index"])
                & (pl.col("minutes_relative") >= 0)
            ).drop_nulls("value")
            assert row["avoided_low"] == bool((post["value"] >= 100).all())


class TestFuelingAggregators:
    def test_timing_effect_validates(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        result = processor.get_fueling_timing_effect()

        FuelingTimingAggregateSchema.validate(result)
        assert set(result["bucket_dim"].unique().to_list()) == {"fueling_time"}
        assert set(result["bucket_key"].to_list()) <= set(FUELING_TIMING_BUCKETS)
        assert (result["actionable"] == (result["n"] >= 8)).all()

    def test_sg_effect_validates(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        result = processor.get_fueling_sg_effect()

        FuelingTimingAggregateSchema.validate(result)
        assert set(result["bucket_dim"].unique().to_list()) == {"fueling_sg"}
        assert set(result["bucket_key"].to_list()) <= set(GLUCOSE_BANDS)

    def test_n_sum_matches_event_count(self, *, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        result = processor.get_fueling_timing_effect()
        events = processor._compute_fueling_event_metrics()  # noqa: SLF001
        assert result["n"].sum() == events.drop_nulls("time_into_run_bucket").height
