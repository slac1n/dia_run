from datetime import datetime, timedelta

import polars as pl

from dia_run.data_models.paths import DataPaths
from dia_run.data_models.questionnaire import QuestionnaireModel
from dia_run.data_models.run_types import RunType
from dia_run.data_processing.data_processing import PRE_RUN_INSULIN_MINUTES, DataProcessor


class TestDataProcessor:
    def test_get_summary(self, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        result = processor.get_summary()

        assert isinstance(result, pl.DataFrame)
        assert len(result) == 3
        assert set(result["activity_id"].to_list()) == {1001, 1002, 1003}

        assert result.filter(pl.col("activity_id") == 1001)["distance"].item() == 5000
        assert result.filter(pl.col("activity_id") == 1002)["distance"].item() == 8000
        assert result.filter(pl.col("activity_id") == 1003)["distance"].item() == 20_000
        assert result.filter(pl.col("activity_id") == 1001)["run_type"].item() == RunType.EASY
        assert result.filter(pl.col("activity_id") == 1002)["run_type"].item() == RunType.INTERVAL
        assert result.filter(pl.col("activity_id") == 1003)["run_type"].item() == RunType.LONG

    def test_get_specific_carelink(self, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        activity_id = 1002
        start_datetime = datetime(2025, 3, 26, 18, 0, 0)
        end_datetime = datetime(2025, 3, 26, 19, 00, 0)

        result = processor.get_specific_carelink(
            activity_id=activity_id, start_datetime=start_datetime, end_datetime=end_datetime
        )
        assert isinstance(result, pl.DataFrame)
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
        result_1 = QuestionnaireModel.model_validate(processor.get_questionnaire(activity_id_1))
        assert len(result_1.pre_run) == 0
        assert len(result_1.basal_adjustments) == 0
        assert len(result_1.fueling_during_run) == 0
        assert len(result_1.bolus) == 0

        activity_id_2 = 1002
        result_2 = QuestionnaireModel.model_validate(processor.get_questionnaire(activity_id_2))
        assert len(result_2.pre_run) == 1
        assert len(result_2.basal_adjustments) == 2
        assert len(result_2.fueling_during_run) == 1
        assert len(result_2.bolus) == 1

        activity_id_3 = 1003
        result_3 = QuestionnaireModel.model_validate(processor.get_questionnaire(activity_id_3))
        assert len(result_3.pre_run) == 1
        assert len(result_3.basal_adjustments) == 0
        assert len(result_3.fueling_during_run) == 2
        assert len(result_3.bolus) == 0

    def test_get_heartrate_streams(self, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)
        result = processor.get_heartrate_streams()

        assert isinstance(result, pl.DataFrame)
        assert set(result["run_type"].to_list()) == {RunType.EASY, RunType.INTERVAL, RunType.LONG}

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

        processor = DataProcessor(test_data_paths)
        result = processor.get_glucose_streams()

        assert isinstance(result, pl.DataFrame)
        assert set(result["run_type"].to_list()) == {RunType.EASY, RunType.INTERVAL, RunType.LONG}

        easy_gs = result.filter(pl.col("run_type") == RunType.EASY)["value"]
        interval_gs = result.filter(pl.col("run_type") == RunType.INTERVAL)["value"]
        long_gs = result.filter(pl.col("run_type") == RunType.LONG)["value"]
        assert easy_gs.mean() < interval_gs.mean() < long_gs.mean()

        for run_type_exp, start_datetime, duration in [
            ((pl.col("run_type") == RunType.EASY), start_datetime_1, duration_1),
            ((pl.col("run_type") == RunType.INTERVAL), start_datetime_2, duration_2),
            ((pl.col("run_type") == RunType.LONG), start_datetime_3, duration_3),
        ]:
            # Should only include data from 5 minutes before start to 5 minutes after end
            result_run_type = result.filter(run_type_exp)
            assert result_run_type["datetime"].max() <= start_datetime + duration + timedelta(minutes=5)
            assert result_run_type["datetime"].min() >= start_datetime - timedelta(minutes=5)

        # Check that 0.0 values for CGM are replaced with None
        assert result.filter(pl.col("value") == 0.0).height == 0
