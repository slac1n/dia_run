from dia_run.data_models.paths import DataPaths
from dia_run.data_processing.data_processing import DataProcessor
from dia_run.llm.run_context import build_run_context


class TestBuildRunContext:
    def test_context_includes_expected_sections(self, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)

        text = build_run_context(processor=processor, activity_id=1001)

        assert "Metadata" in text
        assert "Glucose summary (run window)" in text
        assert "Questionnaire (user-entered context)" in text
        assert "Carelink events" in text
        assert "Heartrate stream during the run" in text
        assert "activity_id: 1001" in text

    def test_context_raises_for_unknown_activity(self, test_data_paths: DataPaths) -> None:
        processor = DataProcessor(test_data_paths)

        try:
            build_run_context(processor=processor, activity_id=999_999)
        except ValueError as exc:
            assert "999999" in str(exc)
        else:
            raise AssertionError("Expected ValueError for unknown activity_id")
