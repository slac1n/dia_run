import json
from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest
from fastapi.testclient import TestClient

from dia_run.data_fetcher.mock_fetcher import MockDataFetcher
from dia_run.data_models.paths import DataPaths
from dia_run.data_models.schemas import SpecificCarelinkSchema
from dia_run.settings import AppSettings
from dia_run.web.app import app
from dia_run.web.dependencies import get_data_fetcher_service, get_data_paths


class TestAppSettings:
    def test_default_mock_data_is_false(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            settings = AppSettings(use_mock_data=False)
        assert settings.use_mock_data is False

    def test_mock_data_enabled(self) -> None:
        settings = AppSettings(use_mock_data=True)
        assert settings.use_mock_data is True

    def test_mock_data_from_env(self) -> None:
        with patch.dict("os.environ", {"USE_MOCK_DATA": "true"}):
            settings = AppSettings()
        assert settings.use_mock_data is True


class TestGetDataPaths:
    def test_returns_default_paths_when_mock_disabled(self) -> None:
        with patch("dia_run.web.dependencies.settings") as mock_settings:
            mock_settings.use_mock_data = False
            from dia_run.web.dependencies import get_data_paths

            paths = get_data_paths()
        assert paths.strava_summary == Path("data") / "strava" / "summary"

    def test_returns_mock_paths_when_mock_enabled(self) -> None:
        with patch("dia_run.web.dependencies.settings") as mock_settings:
            mock_settings.use_mock_data = True
            from dia_run.web.dependencies import get_data_paths

            paths = get_data_paths()
        assert "mock-data" in str(paths.strava_summary)
        assert "mock-data" in str(paths.carelink)
        assert "mock-data" in str(paths.strava_stream)
        assert "mock-data" in str(paths.questionnaire)


class TestMockDataFetcher:
    @pytest.fixture
    def mock_data_paths(self, *, tmp_path: Path) -> DataPaths:
        return DataPaths(
            strava_summary=tmp_path / "strava" / "summary",
            strava_stream=tmp_path / "strava" / "stream",
            carelink=tmp_path / "carelink",
            questionnaire=tmp_path / "questionnaire",
        )

    def test_fetch_creates_delta_tables(self, *, mock_data_paths: DataPaths) -> None:
        fetcher = MockDataFetcher(data_paths=mock_data_paths)
        fetcher.fetch_latest_data_and_save()

        assert (mock_data_paths.strava_summary / "_delta_log").is_dir()
        assert (mock_data_paths.strava_stream / "_delta_log").is_dir()
        assert (mock_data_paths.carelink / "_delta_log").is_dir()

    def test_fetch_writes_summary_with_correct_columns(self, *, mock_data_paths: DataPaths) -> None:
        fetcher = MockDataFetcher(data_paths=mock_data_paths)
        fetcher.fetch_latest_data_and_save()

        df = pl.read_delta(str(mock_data_paths.strava_summary))
        expected_cols = {
            "activity_id",
            "name",
            "start_date_local",
            "distance",
            "moving_time",
            "elapsed_time",
            "total_elevation_gain",
            "average_heartrate",
            "max_heartrate",
            "average_speed",
            "max_speed",
            "average_watts",
            "max_watts",
            "kilojoules",
            "average_pace",
            "max_pace",
        }
        assert expected_cols.issubset(set(df.columns))
        assert len(df) == 1

    def test_fetch_writes_streams_with_correct_columns(self, *, mock_data_paths: DataPaths) -> None:
        fetcher = MockDataFetcher(data_paths=mock_data_paths)
        fetcher.fetch_latest_data_and_save()

        df = pl.read_delta(str(mock_data_paths.strava_stream))
        expected_cols = {"datetime", "heartrate", "power", "velocity", "moving", "activity_id", "pace"}
        assert expected_cols.issubset(set(df.columns))
        assert len(df) > 0

    def test_fetch_writes_carelink_with_valid_schema(self, *, mock_data_paths: DataPaths) -> None:
        fetcher = MockDataFetcher(data_paths=mock_data_paths)
        fetcher.fetch_latest_data_and_save()

        df = pl.read_delta(str(mock_data_paths.carelink))
        expected_cols = {"datetime", "type", "value", "activity_id"}
        assert expected_cols.issubset(set(df.columns))
        assert len(df) > 0

        # Validate against Pandera schema
        SpecificCarelinkSchema.validate(df)

    def test_fetch_writes_questionnaire_json(self, *, mock_data_paths: DataPaths) -> None:
        fetcher = MockDataFetcher(data_paths=mock_data_paths)
        fetcher.fetch_latest_data_and_save()

        json_files = list(mock_data_paths.questionnaire.glob("*.json"))
        assert len(json_files) == 1

        with open(json_files[0]) as f:
            data = json.load(f)
        assert "pre_run" in data
        assert "basal_adjustments" in data
        assert "fueling_during_run" in data
        assert "bolus" in data

    def test_fetch_appends_new_activity(self, *, mock_data_paths: DataPaths) -> None:
        fetcher = MockDataFetcher(data_paths=mock_data_paths)
        fetcher.fetch_latest_data_and_save()

        # Fetch again — should append a second activity
        fetcher2 = MockDataFetcher(data_paths=mock_data_paths)
        fetcher2.fetch_latest_data_and_save()

        df = pl.read_delta(str(mock_data_paths.strava_summary))
        assert len(df) == 2
        assert df["activity_id"].n_unique() == 2

    def test_activity_ids_are_consistent_across_tables(self, *, mock_data_paths: DataPaths) -> None:
        fetcher = MockDataFetcher(data_paths=mock_data_paths)
        fetcher.fetch_latest_data_and_save()

        summary_ids = set(pl.read_delta(str(mock_data_paths.strava_summary))["activity_id"].to_list())
        stream_ids = set(pl.read_delta(str(mock_data_paths.strava_stream))["activity_id"].unique().to_list())
        carelink_ids = set(pl.read_delta(str(mock_data_paths.carelink))["activity_id"].unique().to_list())

        assert summary_ids == stream_ids
        assert summary_ids == carelink_ids


class TestFetchRouteWithMockMode:
    @pytest.fixture
    def mock_fetch_data_paths(
        self,
        *,
        tmp_path_factory: pytest.TempPathFactory,
        strava_summary_data: pl.DataFrame,
        carelink_data: pl.DataFrame,
        strava_stream_data: pl.DataFrame,
        questionnaire_data: dict[int, dict],
    ) -> DataPaths:
        root = tmp_path_factory.mktemp("mock_fetch")
        data_paths = DataPaths(
            carelink=root / "carelink",
            strava_summary=root / "strava" / "summary",
            strava_stream=root / "strava" / "stream",
            questionnaire=root / "questionnaire",
        )
        data_paths.carelink.mkdir(parents=True)
        data_paths.strava_summary.mkdir(parents=True)
        data_paths.strava_stream.mkdir(parents=True)
        data_paths.questionnaire.mkdir(parents=True)

        strava_summary_data.write_delta(str(data_paths.strava_summary))
        carelink_data.write_delta(str(data_paths.carelink))
        strava_stream_data.write_delta(str(data_paths.strava_stream))
        for activity_id, data in questionnaire_data.items():
            with open(data_paths.questionnaire / f"{activity_id}.json", "w") as f:
                json.dump(data, f)

        return data_paths

    @pytest.fixture
    def mock_client(self, *, mock_fetch_data_paths: DataPaths) -> TestClient:
        mock_fetcher = MockDataFetcher(data_paths=mock_fetch_data_paths)
        app.dependency_overrides[get_data_paths] = lambda: mock_fetch_data_paths
        app.dependency_overrides[get_data_fetcher_service] = lambda: mock_fetcher
        with TestClient(app) as test_client:
            yield test_client
        app.dependency_overrides.clear()

    def test_fetch_route_uses_mock_fetcher(self, *, mock_client: TestClient) -> None:
        response = mock_client.post("/fetch", follow_redirects=False)
        assert response.status_code == 303
        assert "questionnaire" in response.headers["location"]
