from datetime import datetime, timedelta

import polars as pl

from dia_run.data_models.kpis import KpiModel
from dia_run.data_models.paths import DataPaths
from dia_run.data_models.run_types import RunType
from dia_run.data_models.schemas import (
    FuelingGlucoseWindowSchema,
    FuelingImpactSchema,
    GlucoseStreamsSchema,
    HeartrateStreamsSchema,
    PreRunNutritionSummarySchema,
    SpecificCarelinkSchema,
    SummarySchema,
)
from dia_run.data_processing.data_processing import PRE_RUN_INSULIN_MINUTES, DataProcessor


class TestDataProcessor:
    def test_get_summary(self, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        result = processor.get_summary()

        SummarySchema.validate(result)
        assert len(result) == 4
        assert set(result["activity_id"].to_list()) == {1001, 1002, 1003, 1004}

        assert result.filter(pl.col("activity_id") == 1001)["distance"].item() == 5000
        assert result.filter(pl.col("activity_id") == 1002)["distance"].item() == 8000
        assert result.filter(pl.col("activity_id") == 1003)["distance"].item() == 20_000
        assert result.filter(pl.col("activity_id") == 1004)["distance"].item() == 42195
        assert result.filter(pl.col("activity_id") == 1001)["run_type"].item() == RunType.EASY
        assert result.filter(pl.col("activity_id") == 1002)["run_type"].item() == RunType.INTERVAL
        assert result.filter(pl.col("activity_id") == 1003)["run_type"].item() == RunType.LONG
        assert result.filter(pl.col("activity_id") == 1004)["run_type"].item() == RunType.RACE

        # Verify human_readable_time has proper zero-padding (H:MM format)
        # Activity 1001: 1800 seconds = 0:30 -> "0:30"
        assert result.filter(pl.col("activity_id") == 1001)["human_readable_time"].item() == "0:30"
        # Activity 1002: 3600 seconds = 1:00 -> "1:00"
        assert result.filter(pl.col("activity_id") == 1002)["human_readable_time"].item() == "1:00"
        # Activity 1003: 7200 seconds = 2:00 -> "2:00"
        assert result.filter(pl.col("activity_id") == 1003)["human_readable_time"].item() == "2:00"
        # Activity 1004: 9000 seconds = 2:30 -> "2:30"
        assert result.filter(pl.col("activity_id") == 1004)["human_readable_time"].item() == "2:30"

        # Verify human_readable_pace has proper zero-padding (M:SS format)
        # Activity 1001: 5.5 min/km = 5:30 -> "5:30"
        assert result.filter(pl.col("activity_id") == 1001)["human_readable_pace"].item() == "5:30"
        # Activity 1002: 5.13 min/km = 5:08 -> "5:08" (tests leading zero in seconds)
        assert result.filter(pl.col("activity_id") == 1002)["human_readable_pace"].item() == "5:08"
        # Activity 1003: 6.0 min/km = 6:00 -> "6:00"
        assert result.filter(pl.col("activity_id") == 1003)["human_readable_pace"].item() == "6:00"
        # Activity 1004: 6.17 min/km = 6:10 -> "6:10"
        assert result.filter(pl.col("activity_id") == 1004)["human_readable_pace"].item() == "6:10"

    def test_get_specific_carelink(self, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        activity_id = 1002
        start_datetime = datetime(2025, 3, 26, 18, 0, 0)
        end_datetime = datetime(2025, 3, 26, 19, 00, 0)

        result = processor.get_specific_carelink(
            activity_id=activity_id, start_datetime=start_datetime, end_datetime=end_datetime
        )
        SpecificCarelinkSchema.validate(result)
        assert set(result["type"].to_list()) == {"INSULIN", "AUTO_BASAL_DELIVERY", "CGM"}
        assert result.filter(pl.col("type") == "INSULIN").height == 1
        assert result.filter(pl.col("type") == "AUTO_BASAL_DELIVERY").height == 35
        assert result.filter(pl.col("type") == "CGM").height == 49

        # Should only include data from PRE_RUN_INSULIN_MINUTES before start to 5 minutes after end
        min_expected_time = start_datetime - timedelta(minutes=PRE_RUN_INSULIN_MINUTES)
        max_expected_time = end_datetime + timedelta(minutes=5)
        assert result["datetime"].min() >= min_expected_time
        assert result["datetime"].max() <= max_expected_time

        # Check that 0.0 values for CGM are replaced with None
        assert result.filter((pl.col("type") == "CGM") & (pl.col("value") == 0.0)).height == 0

    def test_get_questionnaire(self, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)

        activity_id_1 = 1001
        result_1 = processor.get_questionnaire(activity_id_1)
        assert len(result_1.pre_run) == 0
        assert len(result_1.basal_adjustments) == 0
        assert len(result_1.fueling_during_run) == 0
        assert len(result_1.bolus) == 0

        activity_id_2 = 1002
        result_2 = processor.get_questionnaire(activity_id_2)
        assert len(result_2.pre_run) == 1
        assert len(result_2.basal_adjustments) == 2
        assert len(result_2.fueling_during_run) == 1
        assert len(result_2.bolus) == 1

        activity_id_3 = 1003
        result_3 = processor.get_questionnaire(activity_id_3)
        assert len(result_3.pre_run) == 1
        assert len(result_3.basal_adjustments) == 0
        assert len(result_3.fueling_during_run) == 2
        assert len(result_3.bolus) == 0

    def test_get_heartrate_streams(self, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        result = processor.get_heartrate_streams()

        HeartrateStreamsSchema.validate(result)
        assert set(result["run_type"].to_list()) == {RunType.EASY, RunType.INTERVAL, RunType.LONG, RunType.RACE}

        easy_hrs = result.filter(pl.col("run_type") == RunType.EASY)["heartrate"]
        interval_hrs = result.filter(pl.col("run_type") == RunType.INTERVAL)["heartrate"]
        long_hrs = result.filter(pl.col("run_type") == RunType.LONG)["heartrate"]
        assert easy_hrs.mean() < long_hrs.mean() < interval_hrs.mean()

    def test_get_glucose_streams(self, test_data_paths: DataPaths) -> None:
        start_datetime_1 = datetime(2025, 3, 25, 10, 0, 0)
        duration_1 = timedelta(minutes=30)

        start_datetime_2 = datetime(2025, 3, 26, 18, 0, 0)
        duration_2 = timedelta(minutes=60)

        start_datetime_3 = datetime(2025, 3, 27, 14, 0, 0)
        duration_3 = timedelta(minutes=120)

        start_datetime_4 = datetime(2025, 3, 28, 8, 0, 0)
        duration_4 = timedelta(minutes=150)

        processor = DataProcessor(test_data_paths)
        result = processor.get_glucose_streams()

        GlucoseStreamsSchema.validate(result)
        assert set(result["run_type"].to_list()) == {RunType.EASY, RunType.INTERVAL, RunType.LONG, RunType.RACE}

        easy_gs = result.filter(pl.col("run_type") == RunType.EASY)["value"]
        interval_gs = result.filter(pl.col("run_type") == RunType.INTERVAL)["value"]
        long_gs = result.filter(pl.col("run_type") == RunType.LONG)["value"]
        assert easy_gs.mean() < interval_gs.mean() < long_gs.mean()

        for run_type_exp, start_datetime, duration in [
            ((pl.col("run_type") == RunType.EASY), start_datetime_1, duration_1),
            ((pl.col("run_type") == RunType.INTERVAL), start_datetime_2, duration_2),
            ((pl.col("run_type") == RunType.LONG), start_datetime_3, duration_3),
            ((pl.col("run_type") == RunType.RACE), start_datetime_4, duration_4),
        ]:
            # Should only include data from 5 minutes before start to 5 minutes after end
            result_run_type = result.filter(run_type_exp)
            assert result_run_type["datetime"].max() <= start_datetime + duration + timedelta(minutes=5)
            assert result_run_type["datetime"].min() >= start_datetime - timedelta(minutes=5)

        # Check that 0.0 values for CGM are replaced with None
        assert result.filter(pl.col("value") == 0.0).height == 0

    def test_get_pre_run_nutrition_summary(self, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        result = processor.get_pre_run_nutrition_summary()

        PreRunNutritionSummarySchema.validate(result)

        # Activity 1001 has no pre-run nutrition -> excluded
        assert 1001 not in result["activity_id"].to_list()
        assert len(result) == 3

        # Activity 1002: 30g carbs, -30 min, 70% bolus
        row_1002 = result.filter(pl.col("activity_id") == 1002)
        assert row_1002["total_carbohydrates_g"].item() == 30
        assert row_1002["earliest_time_before_start_min"].item() == -30
        assert row_1002["avg_bolus_percentage"].item() == 70.0
        assert row_1002["in_going_sg"].item() is not None
        assert row_1002["in_going_sg"].item() > 0

        # Activity 1003: 40g carbs, -60 min, 80% bolus
        row_1003 = result.filter(pl.col("activity_id") == 1003)
        assert row_1003["total_carbohydrates_g"].item() == 40
        assert row_1003["earliest_time_before_start_min"].item() == -60
        assert row_1003["avg_bolus_percentage"].item() == 80.0
        assert row_1003["in_going_sg"].item() is not None
        assert row_1003["in_going_sg"].item() > 0

        # Activity 1004: 60g carbs, -120 min, 60% bolus
        row_1004 = result.filter(pl.col("activity_id") == 1004)
        assert row_1004["total_carbohydrates_g"].item() == 60
        assert row_1004["earliest_time_before_start_min"].item() == -120
        assert row_1004["avg_bolus_percentage"].item() == 60.0
        assert row_1004["in_going_sg"].item() is not None
        assert row_1004["in_going_sg"].item() > 0

    def test_get_pre_run_nutrition_summary_empty(self, test_data_paths: DataPaths) -> None:
        empty_questionnaire_dir = test_data_paths.questionnaire.parent / "empty_questionnaires"
        empty_questionnaire_dir.mkdir(parents=True, exist_ok=True)

        empty_paths = DataPaths(
            carelink=test_data_paths.carelink,
            strava_summary=test_data_paths.strava_summary,
            strava_stream=test_data_paths.strava_stream,
            questionnaire=empty_questionnaire_dir,
        )
        processor = DataProcessor(empty_paths)
        result = processor.get_pre_run_nutrition_summary()

        PreRunNutritionSummarySchema.validate(result)
        assert result.is_empty()
        assert set(result.columns) == {
            "activity_id",
            "total_carbohydrates_g",
            "earliest_time_before_start_min",
            "avg_bolus_percentage",
            "in_going_sg",
            "name_date",
        }


class TestKpis:
    def test_get_30_day_kpis(self, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        # All 4 test activities are on March 25-28, 2025
        result = processor.get_30_day_kpis(reference_date=datetime(2025, 3, 28))

        assert isinstance(result, KpiModel)

        # Total distance: (5000 + 8000 + 20000 + 42195) / 1000 = 75.195 km -> 75.2 km
        assert result.total_distance_km == 75.2

        # Total running time: (1800 + 3600 + 7200 + 9000) / 60 = 360 minutes
        assert result.total_running_time_minutes == 360

        # Avg sensor glucose should be present and positive
        assert result.avg_sensor_glucose is not None
        assert result.avg_sensor_glucose > 0

        # Time in range should be present (percentage 0-100)
        assert result.time_in_range_percentage is not None
        assert 0 <= result.time_in_range_percentage <= 100

    def test_get_30_day_kpis_no_data(self, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        # Reference date where 30-day window starts after all test activities (March 25-27)
        result = processor.get_30_day_kpis(reference_date=datetime(2025, 5, 1))

        assert isinstance(result, KpiModel)
        assert result.total_distance_km == 0.0
        assert result.total_running_time_minutes == 0
        assert result.avg_sensor_glucose is None
        assert result.time_in_range_percentage is None

    def test_kpi_model_formatted_running_time(self) -> None:
        kpis = KpiModel(
            total_distance_km=75.2,
            total_running_time_minutes=360,
            avg_sensor_glucose=150.0,
            time_in_range_percentage=66.7,
        )
        assert kpis.formatted_running_time == "6h 0m"

        kpis_zero = KpiModel(
            total_distance_km=0.0,
            total_running_time_minutes=0,
            avg_sensor_glucose=None,
            time_in_range_percentage=None,
        )
        assert kpis_zero.formatted_running_time == "0h 0m"


class TestFuelingGlucoseWindows:
    def test_get_fueling_glucose_windows(self, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        result = processor.get_fueling_glucose_windows()

        FuelingGlucoseWindowSchema.validate(result)

        # Activity 1001 has no fueling -> excluded
        assert 1001 not in result["activity_id"].to_list()

        # Activity 1002 has 1 fueling event (at +15 min), run ends at +60 min
        # Window: -15 min to +45 min (relative to fueling)
        events_1002 = result.filter(pl.col("activity_id") == 1002)
        assert set(events_1002["fueling_index"].unique().to_list()) == {0}
        assert events_1002["minutes_relative"].min() >= -15.0
        assert events_1002["minutes_relative"].max() <= 45.0

        # Activity 1003 has 2 fueling events (at +15 and +30 min)
        events_1003 = result.filter(pl.col("activity_id") == 1003)
        assert set(events_1003["fueling_index"].unique().to_list()) == {0, 1}

        # Fueling 0: truncated at next intake (+30 min), so max relative = 15 min
        event_0 = events_1003.filter(pl.col("fueling_index") == 0)
        assert not event_0.is_empty()
        assert event_0["minutes_relative"].min() >= -15.0
        assert event_0["minutes_relative"].max() <= 15.0

        # Fueling 1: window from +30 to min(+30+45=+75, +120) = +75, so max relative = 45 min
        event_1 = events_1003.filter(pl.col("fueling_index") == 1)
        assert not event_1.is_empty()
        assert event_1["minutes_relative"].min() >= -15.0
        assert event_1["minutes_relative"].max() <= 45.0

    def test_get_fueling_glucose_windows_time_alignment(self, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        result = processor.get_fueling_glucose_windows()

        # Activity 1002: fueling at +15 min from start (18:15)
        # First CGM point should be at or near minute_relative=-15 (15 min before fueling)
        events_1002 = result.filter((pl.col("activity_id") == 1002) & (pl.col("fueling_index") == 0)).sort(
            "minutes_relative"
        )
        first_min_rel = events_1002["minutes_relative"].head(1).item()
        assert first_min_rel == -15.0  # CGM exists at -15 min relative to fueling (15 min before intake)

    def test_get_fueling_glucose_windows_no_post_run_data(self, test_data_paths: DataPaths) -> None:
        """Windows must not include any glucose data after the activity end time."""
        processor = DataProcessor(test_data_paths)
        result = processor.get_fueling_glucose_windows()

        # Activity 1002: run is 60 min, fueling at +15 min, window max = 45 min from fueling
        # So absolute max datetime = 18:15 + 45min = 19:00 = run end. No post-run.
        events_1002 = result.filter(pl.col("activity_id") == 1002)
        assert events_1002["minutes_relative"].max() <= 45.0

        # Activity 1003: run is 120 min, fueling 1 at +30 min, window = 45 min
        # Absolute max datetime = 14:30 + 45min = 15:15, well within 16:00 end
        events_1003_f1 = result.filter((pl.col("activity_id") == 1003) & (pl.col("fueling_index") == 1))
        assert events_1003_f1["minutes_relative"].max() <= 45.0

    def test_get_fueling_glucose_windows_empty(self, test_data_paths: DataPaths) -> None:
        empty_questionnaire_dir = test_data_paths.questionnaire.parent / "empty_questionnaires_fuel"
        empty_questionnaire_dir.mkdir(parents=True, exist_ok=True)

        empty_paths = DataPaths(
            carelink=test_data_paths.carelink,
            strava_summary=test_data_paths.strava_summary,
            strava_stream=test_data_paths.strava_stream,
            questionnaire=empty_questionnaire_dir,
        )
        processor = DataProcessor(empty_paths)
        result = processor.get_fueling_glucose_windows()

        FuelingGlucoseWindowSchema.validate(result)
        assert result.is_empty()
        assert set(result.columns) == {"activity_id", "fueling_index", "minutes_relative", "value"}


class TestFuelingImpact:
    def test_get_fueling_impact(self, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        result = processor.get_fueling_impact()

        FuelingImpactSchema.validate(result)

        # Activity 1001 has no fueling -> excluded
        assert 1001 not in result["activity_id"].to_list()

        # Should have 5 fueling events total: 1 from 1002, 2 from 1003, 2 from 1004
        assert len(result) == 5

    def test_get_fueling_impact_activity_1002(self, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        result = processor.get_fueling_impact()

        # Activity 1002: 15g Energy Gel at +15 min, run ends at +60 min
        # Window is capped to activity end (45 min of data)
        # CGM values decline during this window (no rise in in-run data)
        row_1002 = result.filter((pl.col("activity_id") == 1002) & (pl.col("fueling_index") == 0))
        assert row_1002["carbohydrates_g"].item() == 15
        assert row_1002["baseline_sg"].item() is not None
        assert row_1002["baseline_sg"].item() > 0

        # Peak and baseline are computed from in-run data only
        assert row_1002["peak_sg"].item() is not None
        assert row_1002["time_to_peak_min"].item() is not None

    def test_get_fueling_impact_activity_1003(self, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        result = processor.get_fueling_impact()

        # Activity 1003: 2 fueling events
        events_1003 = result.filter(pl.col("activity_id") == 1003)
        assert len(events_1003) == 2

        # Fueling 0: 20g Energy Gel at +15 min (window truncated at +30 min = 15 min of data)
        fuel_0 = events_1003.filter(pl.col("fueling_index") == 0)
        assert fuel_0["carbohydrates_g"].item() == 20

        # Fueling 1: 25g Sports Drink at +30 min (window = 45 min of data)
        fuel_1 = events_1003.filter(pl.col("fueling_index") == 1)
        assert fuel_1["carbohydrates_g"].item() == 25

        # Both should have baseline values
        for fuel in [fuel_0, fuel_1]:
            assert fuel["baseline_sg"].item() is not None
            assert fuel["peak_sg"].item() is not None

    def test_get_fueling_impact_windows_respect_activity_end(self, test_data_paths: DataPaths) -> None:
        """Peak values should come from in-run data only (no post-activity data)."""
        processor = DataProcessor(test_data_paths)
        result = processor.get_fueling_impact()

        # Activity 1002: window includes 15 min pre-intake (-15 to 0) + 45 min post-intake (0 to +45, clamped to +45)
        # Pre-intake CGM values: 140.0 at -15 min (first in window)
        # In-run CGM values from fueling time (i=15) to end (i=60) are 140.0 - i/10, declining from 138.5 to 134.0
        # Peak = 140.0 at minute -15 (pre-intake)
        row_1002 = result.filter((pl.col("activity_id") == 1002) & (pl.col("fueling_index") == 0))
        assert row_1002["peak_sg"].item() == 140.0
        assert row_1002["time_to_peak_min"].item() == -15.0

    def test_get_fueling_impact_overlapping_windows_truncated(self, test_data_paths: DataPaths) -> None:
        """First fueling window should be truncated at the next fueling time."""
        processor = DataProcessor(test_data_paths)
        result = processor.get_fueling_impact()

        # Activity 1003, fueling 0: window is only 15 min (truncated at next intake at +30 min)
        # CGM values are all 170.0 in this flat window
        fuel_0 = result.filter((pl.col("activity_id") == 1003) & (pl.col("fueling_index") == 0))
        assert fuel_0["peak_sg"].item() == 170.0
        assert fuel_0["baseline_sg"].item() == 170.0
        assert fuel_0["peak_increase"].item() == 0.0

    def test_get_fueling_impact_empty(self, test_data_paths: DataPaths) -> None:
        empty_questionnaire_dir = test_data_paths.questionnaire.parent / "empty_questionnaires_impact"
        empty_questionnaire_dir.mkdir(parents=True, exist_ok=True)

        empty_paths = DataPaths(
            carelink=test_data_paths.carelink,
            strava_summary=test_data_paths.strava_summary,
            strava_stream=test_data_paths.strava_stream,
            questionnaire=empty_questionnaire_dir,
        )
        processor = DataProcessor(empty_paths)
        result = processor.get_fueling_impact()

        FuelingImpactSchema.validate(result)
        assert result.is_empty()
        assert set(result.columns) == {
            "activity_id",
            "fueling_index",
            "carbohydrates_g",
            "baseline_sg",
            "peak_sg",
            "peak_increase",
            "time_to_peak_min",
            "name_date",
        }
