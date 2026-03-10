from pathlib import Path
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from dia_run.data_fetcher.live_fetcher import LiveDataFetcher
from dia_run.data_models.api_responses import CareLinkResponse
from dia_run.data_models.paths import DataPaths


def _build_carelink_payload(*, sg_values: list[int | float | None]) -> dict[str, object]:
    sgs = [
        {"timestamp": f"2026-03-10T18:{index:02d}:00", "sg": value} for index, value in enumerate(sg_values, start=1)
    ]
    return {
        "patientData": {
            "sgs": sgs,
            "markers": [
                {
                    "timestamp": "2026-03-10T18:00:00",
                    "type": "INSULIN",
                    "data": {"dataValues": {"deliveredFastAmount": 0.5}},
                }
            ],
        }
    }


class TestCareLinkResponse:
    def test_zero_sg_is_treated_as_missing_data(self) -> None:
        payload = _build_carelink_payload(sg_values=[0, 145])

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
        payload = _build_carelink_payload(sg_values=[0, 145])
        mock_client = MagicMock()
        mock_client.init.return_value = True
        mock_client.getRecentData.return_value = payload

        with patch("dia_run.data_fetcher.live_fetcher.CareLinkClient", return_value=mock_client):
            fetcher = LiveDataFetcher(data_paths=data_paths)
            fetcher.latest_activity_id = 1234
            fetcher.activity_id_list = []

            df = fetcher._get_carelink_data()

        assert df is not None
        cgm_df = df.filter(pl.col("type") == "CGM").sort("datetime")
        assert cgm_df["value"].to_list() == [None, 145.0]
