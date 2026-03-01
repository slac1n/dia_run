import json

import polars as pl
import pytest
from fastapi.testclient import TestClient

from dia_run.data_models.paths import DataPaths
from dia_run.web.app import app
from dia_run.web.dependencies import get_data_paths


@pytest.fixture
def status_data_paths(
    *,
    tmp_path_factory: pytest.TempPathFactory,
    strava_summary_data: pl.DataFrame,
    carelink_data: pl.DataFrame,
    strava_stream_data: pl.DataFrame,
    questionnaire_data: dict[int, dict],
) -> DataPaths:
    root = tmp_path_factory.mktemp("questionnaire_status_data")
    carelink_dir = root / "carelink"
    strava_summary_dir = root / "strava" / "summary"
    strava_stream_dir = root / "strava" / "stream"
    questionnaire_dir = root / "run_questionnaires"

    carelink_dir.mkdir(parents=True, exist_ok=True)
    strava_summary_dir.mkdir(parents=True, exist_ok=True)
    strava_stream_dir.mkdir(parents=True, exist_ok=True)
    questionnaire_dir.mkdir(parents=True, exist_ok=True)

    data_paths = DataPaths(
        carelink=carelink_dir,
        strava_summary=strava_summary_dir,
        strava_stream=strava_stream_dir,
        questionnaire=questionnaire_dir,
    )

    strava_summary_data.write_delta(str(data_paths.strava_summary))
    carelink_data.write_delta(str(data_paths.carelink))
    strava_stream_data.write_delta(str(data_paths.strava_stream))
    for activity_id, payload in questionnaire_data.items():
        with open(data_paths.questionnaire / f"{activity_id}.json", "w") as file_handle:
            json.dump(payload, file_handle)

    return data_paths


@pytest.fixture
def client(*, status_data_paths: DataPaths) -> TestClient:
    app.dependency_overrides[get_data_paths] = lambda: status_data_paths
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_questionnaire_status_counts_unannotated(*, client: TestClient, status_data_paths: DataPaths) -> None:
    response = client.get("/questionnaire/status")
    assert response.status_code == 200
    assert response.json() == {"unannotated_count": 0}

    (status_data_paths.questionnaire / "1004.json").unlink(missing_ok=True)

    response = client.get("/questionnaire/status")
    assert response.status_code == 200
    assert response.json() == {"unannotated_count": 1}
