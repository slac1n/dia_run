from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
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

    def test_accepts_calibration_marker_type(self) -> None:
        activity_start = datetime(2026, 3, 10, 18, 0, 0)
        payload = _build_carelink_payload(
            sgs=[
                (activity_start + timedelta(minutes=1), 145),
            ],
            markers=[_build_marker(timestamp=activity_start, marker_type="CALIBRATION")],
        )

        response = CareLinkResponse(**payload)

        assert response.patientData.markers[0].type == "CALIBRATION"

    def test_allows_sg_entry_without_timestamp(self) -> None:
        payload: dict[str, Any] = {
            "patientData": {
                "sgs": [{"kind": "SG", "version": 1, "sg": 0}],
                "markers": [],
            }
        }

        response = CareLinkResponse(**payload)

        assert response.patientData.sgs[0].timestamp is None


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

        with (
            patch("dia_run.data_fetcher.live_fetcher.CareLinkClient", return_value=mock_client),
            patch.object(
                LiveDataFetcher,
                "_get_current_server_time",
                return_value=activity_start + timedelta(minutes=5),
            ),
        ):
            fetcher = LiveDataFetcher(data_paths=data_paths)
            fetcher.latest_activity_id = 1234
            fetcher.activity_id_list = []
            fetcher.latest_activity_start_datetime = activity_start
            fetcher.latest_activity_end_datetime = activity_start + timedelta(minutes=30)

            df = fetcher._get_carelink_data()

        assert df is not None
        cgm_df = df.filter(pl.col("type") == "CGM").sort("datetime")
        assert cgm_df["value"].to_list() == [None, 145.0]

    def test_get_carelink_data_keeps_calibration_markers_with_null_value(self, *, data_paths: DataPaths) -> None:
        activity_start = datetime(2026, 3, 10, 18, 0, 0)
        payload = _build_carelink_payload(
            sgs=[
                (activity_start + timedelta(minutes=1), 140),
            ],
            markers=[_build_marker(timestamp=activity_start, marker_type="CALIBRATION")],
        )
        mock_client = MagicMock()
        mock_client.init.return_value = True
        mock_client.getRecentData.return_value = payload

        with (
            patch("dia_run.data_fetcher.live_fetcher.CareLinkClient", return_value=mock_client),
            patch.object(
                LiveDataFetcher,
                "_get_current_server_time",
                return_value=activity_start + timedelta(minutes=5),
            ),
        ):
            fetcher = LiveDataFetcher(data_paths=data_paths)
            fetcher.latest_activity_id = 1234
            fetcher.activity_id_list = []
            fetcher.latest_activity_start_datetime = activity_start
            fetcher.latest_activity_end_datetime = activity_start + timedelta(minutes=30)

            df = fetcher._get_carelink_data()

        assert df is not None
        calibration_df = df.filter(pl.col("type") == "CALIBRATION")
        assert calibration_df.height == 1
        assert calibration_df["value"].item() is None

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
            patch.object(
                LiveDataFetcher,
                "_get_current_server_time",
                return_value=activity_end + timedelta(minutes=20),
            ),
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

        with (
            patch("dia_run.data_fetcher.live_fetcher.CareLinkClient", return_value=mock_client),
            patch.object(
                LiveDataFetcher,
                "_get_current_server_time",
                return_value=activity_end + timedelta(minutes=61),
            ),
        ):
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

    def test_get_carelink_data_continues_when_latest_cgm_timestamp_is_stale_with_temporary_ignore(
        self, *, data_paths: DataPaths
    ) -> None:
        activity_start = datetime(2026, 3, 10, 18, 0, 0)
        payload = _build_carelink_payload(
            sgs=[
                (activity_start - timedelta(hours=3), 100.0),
                (activity_start - timedelta(hours=2, minutes=1), 105.0),
            ],
            markers=[_build_marker(timestamp=activity_start - timedelta(minutes=5), amount=1.0)],
        )
        mock_client = MagicMock()
        mock_client.init.return_value = True
        mock_client.getRecentData.return_value = payload

        with (
            patch("dia_run.data_fetcher.live_fetcher.CareLinkClient", return_value=mock_client),
            patch.object(live_fetcher_module.settings, "carelink_stale_threshold_minutes", 120),
            patch.object(live_fetcher_module.settings, "server_timezone", "Europe/Berlin"),
            patch.object(
                LiveDataFetcher,
                "_get_current_server_time",
                return_value=activity_start,
            ),
        ):
            fetcher = LiveDataFetcher(data_paths=data_paths)
            fetcher.latest_activity_id = 1234
            fetcher.activity_id_list = []
            fetcher.latest_activity_start_datetime = activity_start
            fetcher.latest_activity_end_datetime = activity_start + timedelta(minutes=30)

            df = fetcher._get_carelink_data()

        assert df is not None

    def test_get_carelink_data_allows_latest_cgm_timestamp_at_threshold(self, *, data_paths: DataPaths) -> None:
        activity_start = datetime(2026, 3, 10, 18, 0, 0)
        payload = _build_carelink_payload(
            sgs=[
                (activity_start - timedelta(hours=2), 110.0),
            ],
            markers=[_build_marker(timestamp=activity_start - timedelta(hours=4), amount=1.0)],
        )
        mock_client = MagicMock()
        mock_client.init.return_value = True
        mock_client.getRecentData.return_value = payload

        with (
            patch("dia_run.data_fetcher.live_fetcher.CareLinkClient", return_value=mock_client),
            patch.object(live_fetcher_module.settings, "carelink_stale_threshold_minutes", 120),
            patch.object(live_fetcher_module.settings, "server_timezone", "Europe/Berlin"),
            patch.object(
                LiveDataFetcher,
                "_get_current_server_time",
                return_value=activity_start,
            ),
        ):
            fetcher = LiveDataFetcher(data_paths=data_paths)
            fetcher.latest_activity_id = 1234
            fetcher.activity_id_list = []
            fetcher.latest_activity_start_datetime = activity_start - timedelta(hours=1)
            fetcher.latest_activity_end_datetime = activity_start

            df = fetcher._get_carelink_data()

        assert df is not None

    def test_get_carelink_data_uses_latest_cgm_timestamp_only_for_staleness_with_temporary_ignore(
        self, *, data_paths: DataPaths
    ) -> None:
        activity_start = datetime(2026, 3, 10, 18, 0, 0)
        payload = _build_carelink_payload(
            sgs=[
                (activity_start - timedelta(hours=2, minutes=1), 110.0),
            ],
            markers=[_build_marker(timestamp=activity_start - timedelta(minutes=5), amount=1.0)],
        )
        mock_client = MagicMock()
        mock_client.init.return_value = True
        mock_client.getRecentData.return_value = payload

        with (
            patch("dia_run.data_fetcher.live_fetcher.CareLinkClient", return_value=mock_client),
            patch.object(live_fetcher_module.settings, "carelink_stale_threshold_minutes", 120),
            patch.object(live_fetcher_module.settings, "server_timezone", "Europe/Berlin"),
            patch.object(
                LiveDataFetcher,
                "_get_current_server_time",
                return_value=activity_start,
            ),
        ):
            fetcher = LiveDataFetcher(data_paths=data_paths)
            fetcher.latest_activity_id = 1234
            fetcher.activity_id_list = []
            fetcher.latest_activity_start_datetime = activity_start - timedelta(hours=1)
            fetcher.latest_activity_end_datetime = activity_start

            df = fetcher._get_carelink_data()

        assert df is not None

    def test_get_latest_cgm_timestamp_raises_when_sgs_is_empty(self, *, data_paths: DataPaths) -> None:
        activity_start = datetime(2026, 3, 10, 18, 0, 0)
        payload = _build_carelink_payload(sgs=[], markers=[])
        mock_client = MagicMock()
        mock_client.init.return_value = True
        mock_client.getRecentData.return_value = payload

        with patch("dia_run.data_fetcher.live_fetcher.CareLinkClient", return_value=mock_client):
            fetcher = LiveDataFetcher(data_paths=data_paths)
            fetcher.latest_activity_id = 1234
            fetcher.activity_id_list = []
            fetcher.latest_activity_start_datetime = activity_start
            fetcher.latest_activity_end_datetime = activity_start + timedelta(minutes=30)

            with pytest.raises(ValueError, match="CareLink API response did not include any CGM readings"):
                fetcher._get_carelink_data()

    def test_get_latest_cgm_timestamp_ignores_sgs_without_timestamp(self, *, data_paths: DataPaths) -> None:
        activity_start = datetime(2026, 3, 10, 18, 0, 0)
        payload: dict[str, Any] = {
            "patientData": {
                "sgs": [
                    {"kind": "SG", "version": 1, "sg": 0},
                    {"timestamp": _format_timestamp(value=activity_start + timedelta(minutes=2)), "sg": 145},
                ],
                "markers": [_build_marker(timestamp=activity_start)],
            }
        }
        mock_client = MagicMock()
        mock_client.init.return_value = True
        mock_client.getRecentData.return_value = payload

        with (
            patch("dia_run.data_fetcher.live_fetcher.CareLinkClient", return_value=mock_client),
            patch.object(
                LiveDataFetcher,
                "_get_current_server_time",
                return_value=activity_start + timedelta(minutes=5),
            ),
        ):
            fetcher = LiveDataFetcher(data_paths=data_paths)
            fetcher.latest_activity_id = 1234
            fetcher.activity_id_list = []
            fetcher.latest_activity_start_datetime = activity_start
            fetcher.latest_activity_end_datetime = activity_start + timedelta(minutes=30)

            df = fetcher._get_carelink_data()

        assert df is not None
        cgm_df = df.filter(pl.col("type") == "CGM").sort("datetime")
        assert cgm_df.height == 1
        assert cgm_df["value"].to_list() == [145.0]

    def test_fetch_latest_data_and_save_continues_and_writes_strava_when_carelink_is_stale_with_temporary_ignore(
        self, *, data_paths: DataPaths
    ) -> None:
        fetcher = LiveDataFetcher(data_paths=data_paths)
        summary_df = pl.DataFrame(
            {
                "activity_id": [1234],
                "name": ["Evening Run"],
                "start_date_local": [datetime(2026, 3, 10, 18, 0, 0)],
                "distance": [10000.0],
                "moving_time": [3600],
                "elapsed_time": [3600],
                "total_elevation_gain": [120.0],
                "average_heartrate": [150.0],
                "max_heartrate": [170.0],
                "average_speed": [2.8],
                "max_speed": [4.0],
                "average_watts": [180.0],
                "max_watts": [320.0],
                "kilojoules": [700.0],
                "average_pace": [5.95],
                "max_pace": [4.17],
            }
        )
        stream_df = pl.DataFrame(
            {
                "datetime": [datetime(2026, 3, 10, 18, 0, 0)],
                "heartrate": [150.0],
                "power": [180.0],
                "velocity": [2.8],
                "moving": [True],
                "activity_id": [1234],
                "pace": [5.95],
            }
        )

        with patch.object(fetcher, "_get_strava_data", return_value=(summary_df, stream_df)), patch.object(
            fetcher, "_get_carelink_data", return_value=None
        ):
            result = fetcher.fetch_latest_data_and_save()

        assert result is True
        assert (data_paths.strava_summary / "_delta_log").exists()
        assert (data_paths.strava_stream / "_delta_log").exists()
        assert not (data_paths.carelink / "_delta_log").exists()


class TestLiveDataFetcherStrava:
    @pytest.fixture
    def data_paths(self, *, tmp_path: Path) -> DataPaths:
        return DataPaths(
            strava_summary=tmp_path / "strava" / "summary",
            strava_stream=tmp_path / "strava" / "stream",
            carelink=tmp_path / "carelink",
            questionnaire=tmp_path / "questionnaire",
        )

    def test_process_latest_activity_id_handles_missing_optional_streams(self, *, data_paths: DataPaths) -> None:
        activity_start = datetime(2026, 3, 10, 18, 0, 0)
        client = MagicMock()
        client.get_activity.return_value = SimpleNamespace(
            id=1234,
            name="Indoor Run",
            start_date_local=activity_start,
            distance=5000.0,
            moving_time=1800,
            elapsed_time=1800,
            total_elevation_gain=0.0,
            average_heartrate=150.0,
            max_heartrate=170,
            average_speed=2.8,
            max_speed=3.4,
            average_watts=None,
            max_watts=None,
            kilojoules=None,
        )
        client.get_activity_streams.return_value = {
            "time": SimpleNamespace(data=[0, 1, 2]),
            "velocity_smooth": SimpleNamespace(data=[2.8, 0.8, 3.0]),
            "moving": SimpleNamespace(data=None),
        }

        fetcher = LiveDataFetcher(data_paths=data_paths)
        fetcher.latest_activity_id = 1234

        summary_df, stream_df = fetcher._process_latest_activity_id(client)

        assert summary_df["average_watts"].item() is None
        assert summary_df["max_watts"].item() is None
        assert summary_df["kilojoules"].item() is None
        assert stream_df["power"].to_list() == [None, None, None]
        assert stream_df["heartrate"].to_list() == [None, None, None]
        assert stream_df["moving"].to_list() == [None, None, None]
        assert stream_df["velocity"].to_list() == [2.8, 0.8, 3.0]

        pace_values = stream_df["pace"].to_list()
        assert pace_values[0] == pytest.approx((1000 / 2.8) / 60)
        assert pace_values[1] is None
        assert pace_values[2] == pytest.approx((1000 / 3.0) / 60)

        assert fetcher.latest_activity_start_datetime == activity_start
        assert fetcher.latest_activity_end_datetime == activity_start + timedelta(seconds=1800)

    def test_process_latest_activity_id_returns_empty_streams_when_time_is_missing(
        self, *, data_paths: DataPaths
    ) -> None:
        activity_start = datetime(2026, 3, 10, 18, 0, 0)
        client = MagicMock()
        client.get_activity.return_value = SimpleNamespace(
            id=1234,
            name="Indoor Run",
            start_date_local=activity_start,
            distance=5000.0,
            moving_time=1800,
            elapsed_time=1800,
            total_elevation_gain=0.0,
            average_heartrate=150.0,
            max_heartrate=170,
            average_speed=2.8,
            max_speed=3.4,
            average_watts=None,
            max_watts=None,
            kilojoules=None,
        )
        client.get_activity_streams.return_value = {
            "watts": SimpleNamespace(data=[200.0, 205.0]),
        }

        fetcher = LiveDataFetcher(data_paths=data_paths)
        fetcher.latest_activity_id = 1234

        summary_df, stream_df = fetcher._process_latest_activity_id(client)

        assert summary_df.height == 1
        assert stream_df.is_empty()
        assert dict(stream_df.schema) == {
            "datetime": pl.Datetime,
            "heartrate": pl.Int64,
            "power": pl.Float64,
            "velocity": pl.Float64,
            "moving": pl.Boolean,
            "activity_id": pl.Int64,
            "pace": pl.Float64,
        }

    def test_fetch_latest_data_and_save_persists_null_power_metrics(self, *, data_paths: DataPaths) -> None:
        activity_start = datetime(2026, 3, 10, 18, 0, 0)
        fetcher = LiveDataFetcher(data_paths=data_paths)
        summary_df = pl.DataFrame(
            {
                "activity_id": [1234],
                "name": ["Indoor Run"],
                "start_date_local": [activity_start],
                "distance": [5000.0],
                "moving_time": [1800],
                "elapsed_time": [1800],
                "total_elevation_gain": [0.0],
                "average_heartrate": [150.0],
                "max_heartrate": [170],
                "average_speed": [2.8],
                "max_speed": [3.4],
                "average_watts": [None],
                "max_watts": [None],
                "kilojoules": [None],
                "average_pace": [(1000 / 2.8) / 60],
                "max_pace": [(1000 / 3.4) / 60],
            }
        ).with_columns(
            pl.col("activity_id").cast(pl.Int64),
            pl.col("start_date_local").cast(pl.Datetime),
            pl.col("distance").cast(pl.Float64),
            pl.col("moving_time").cast(pl.Int64),
            pl.col("elapsed_time").cast(pl.Int64),
            pl.col("total_elevation_gain").cast(pl.Float64),
            pl.col("average_heartrate").cast(pl.Float64),
            pl.col("max_heartrate").cast(pl.Int64),
            pl.col("average_speed").cast(pl.Float64),
            pl.col("max_speed").cast(pl.Float64),
            pl.col("average_watts").cast(pl.Float64),
            pl.col("max_watts").cast(pl.Int64),
            pl.col("kilojoules").cast(pl.Float64),
            pl.col("average_pace").cast(pl.Float64),
            pl.col("max_pace").cast(pl.Float64),
        )
        stream_df = pl.DataFrame(
            {
                "datetime": [activity_start],
                "heartrate": [150],
                "power": [None],
                "velocity": [2.8],
                "moving": [None],
                "activity_id": [1234],
                "pace": [(1000 / 2.8) / 60],
            }
        ).with_columns(
            pl.col("datetime").cast(pl.Datetime),
            pl.col("heartrate").cast(pl.Int64),
            pl.col("power").cast(pl.Float64),
            pl.col("velocity").cast(pl.Float64),
            pl.col("moving").cast(pl.Boolean),
            pl.col("activity_id").cast(pl.Int64),
            pl.col("pace").cast(pl.Float64),
        )
        carelink_df = pl.DataFrame(
            {
                "datetime": [activity_start],
                "type": ["CGM"],
                "value": [145.0],
                "activity_id": [1234],
            }
        ).with_columns(
            pl.col("datetime").cast(pl.Datetime),
            pl.col("value").cast(pl.Float64),
            pl.col("activity_id").cast(pl.Int64),
        )

        with (
            patch.object(fetcher, "_get_strava_data", return_value=(summary_df, stream_df)),
            patch.object(fetcher, "_get_carelink_data", return_value=carelink_df),
        ):
            result = fetcher.fetch_latest_data_and_save()

        assert result is True

        written_summary = pl.read_delta(str(data_paths.strava_summary))
        written_stream = pl.read_delta(str(data_paths.strava_stream))
        assert written_summary["average_watts"].item() is None
        assert written_summary["max_watts"].item() is None
        assert written_summary["kilojoules"].item() is None
        assert written_stream["power"].item() is None
        assert written_stream["moving"].item() is None
