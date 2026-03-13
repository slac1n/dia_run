from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

import dia_run.data_fetcher.live_fetcher as live_fetcher_module
from dia_run.data_fetcher.live_fetcher import LiveDataFetcher
from dia_run.data_models.api_responses import CareLinkResponse
from dia_run.data_models.paths import DataPaths


def _format_timestamp(*, value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S")


def _build_marker(*, timestamp: datetime, marker_type: str = "INSULIN", amount: float = 0.5) -> dict[str, Any]:
    if marker_type == "AUTO_BASAL_DELIVERY":
        data_values = {"bolusAmount": amount}
    else:
        data_values = {"deliveredFastAmount": amount}

    return {
        "timestamp": _format_timestamp(value=timestamp),
        "type": marker_type,
        "data": {"dataValues": data_values},
    }


def _build_carelink_payload(
    *, sgs: list[tuple[datetime, int | float | None]], markers: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "patientData": {
            "sgs": [{"timestamp": _format_timestamp(value=timestamp), "sg": value} for timestamp, value in sgs],
            "markers": markers,
        }
    }


class TestCareLinkResponse:
    def test_zero_sg_is_treated_as_missing_data(self) -> None:
        activity_start = datetime(2026, 3, 10, 18, 0, 0)
        payload = _build_carelink_payload(
            sgs=[
                (activity_start + timedelta(minutes=1), 0),
                (activity_start + timedelta(minutes=2), 145),
            ],
            markers=[_build_marker(timestamp=activity_start)],
        )

        response = CareLinkResponse(**payload)

        assert response.patientData.sgs[0].sg is None
        assert response.patientData.sgs[1].sg == 145.0


class TestLiveDataFetcherCareLink:
    @pytest.fixture
    def data_paths(self, *, tmp_path: Path) -> DataPaths:
        return DataPaths(
            strava_summary=tmp_path / "strava" / "summary",
            strava_stream=tmp_path / "strava" / "stream",
            carelink=tmp_path / "carelink",
            questionnaire=tmp_path / "questionnaire",
        )

    def test_get_carelink_data_keeps_zero_sg_rows_as_null_values(self, *, data_paths: DataPaths) -> None:
        activity_start = datetime(2026, 3, 10, 18, 0, 0)
        payload = _build_carelink_payload(
            sgs=[
                (activity_start + timedelta(minutes=1), 0),
                (activity_start + timedelta(minutes=2), 145),
            ],
            markers=[_build_marker(timestamp=activity_start)],
        )
        mock_client = MagicMock()
        mock_client.init.return_value = True
        mock_client.getRecentData.return_value = payload

        with patch("dia_run.data_fetcher.live_fetcher.CareLinkClient", return_value=mock_client):
            fetcher = LiveDataFetcher(data_paths=data_paths)
            fetcher.latest_activity_id = 1234
            fetcher.activity_id_list = []
            fetcher.latest_activity_start_datetime = activity_start
            fetcher.latest_activity_end_datetime = activity_start + timedelta(minutes=30)

            df = fetcher._get_carelink_data()

        assert df is not None
        cgm_df = df.filter(pl.col("type") == "CGM").sort("datetime")
        assert cgm_df["value"].to_list() == [None, 145.0]

    def test_get_carelink_data_filters_rows_to_configured_workout_window(self, *, data_paths: DataPaths) -> None:
        activity_start = datetime(2026, 3, 10, 18, 0, 0)
        activity_end = datetime(2026, 3, 10, 19, 0, 0)
        payload = _build_carelink_payload(
            sgs=[
                (activity_start - timedelta(minutes=31), 100.0),
                (activity_start - timedelta(minutes=30), 105.0),
                (activity_start, 110.0),
                (activity_end + timedelta(minutes=15), 115.0),
                (activity_end + timedelta(minutes=16), 120.0),
            ],
            markers=[_build_marker(timestamp=activity_start - timedelta(minutes=5), amount=1.0)],
        )
        mock_client = MagicMock()
        mock_client.init.return_value = True
        mock_client.getRecentData.return_value = payload

        with (
            patch("dia_run.data_fetcher.live_fetcher.CareLinkClient", return_value=mock_client),
            patch.object(live_fetcher_module.settings, "carelink_pre_workout_window_minutes", 30),
            patch.object(live_fetcher_module.settings, "carelink_post_workout_window_minutes", 15),
        ):
            fetcher = LiveDataFetcher(data_paths=data_paths)
            fetcher.latest_activity_id = 1234
            fetcher.activity_id_list = []
            fetcher.latest_activity_start_datetime = activity_start
            fetcher.latest_activity_end_datetime = activity_end

            df = fetcher._get_carelink_data()

        assert df is not None
        cgm_df = df.filter(pl.col("type") == "CGM").sort("datetime")
        assert cgm_df["datetime"].to_list() == [
            activity_start - timedelta(minutes=30),
            activity_start,
            activity_end + timedelta(minutes=15),
        ]
        assert df["activity_id"].unique().to_list() == [1234]

    def test_get_carelink_data_keeps_all_rows_when_carelink_returns_less_data_than_window(
        self, *, data_paths: DataPaths
    ) -> None:
        activity_start = datetime(2026, 3, 10, 18, 0, 0)
        activity_end = datetime(2026, 3, 10, 19, 0, 0)
        payload = _build_carelink_payload(
            sgs=[
                (activity_start - timedelta(minutes=60), 100.0),
                (activity_start - timedelta(minutes=30), 105.0),
                (activity_end + timedelta(minutes=60), 115.0),
            ],
            markers=[_build_marker(timestamp=activity_start - timedelta(minutes=45), amount=1.0)],
        )
        mock_client = MagicMock()
        mock_client.init.return_value = True
        mock_client.getRecentData.return_value = payload

        with patch("dia_run.data_fetcher.live_fetcher.CareLinkClient", return_value=mock_client):
            fetcher = LiveDataFetcher(data_paths=data_paths)
            fetcher.latest_activity_id = 1234
            fetcher.activity_id_list = []
            fetcher.latest_activity_start_datetime = activity_start
            fetcher.latest_activity_end_datetime = activity_end

            df = fetcher._get_carelink_data()

        assert df is not None
        cgm_df = df.filter(pl.col("type") == "CGM").sort("datetime")
        assert cgm_df["datetime"].min() == activity_start - timedelta(minutes=60)
        assert cgm_df["datetime"].max() == activity_end + timedelta(minutes=60)
        assert len(cgm_df) == 3

    def test_get_carelink_data_skips_download_when_activity_already_exists(self, *, data_paths: DataPaths) -> None:
        with patch("dia_run.data_fetcher.live_fetcher.CareLinkClient") as mock_client_cls:
            fetcher = LiveDataFetcher(data_paths=data_paths)
            fetcher.latest_activity_id = 1234
            fetcher.activity_id_list = [1234]

            df = fetcher._get_carelink_data()

        assert df is None
        mock_client_cls.assert_not_called()
