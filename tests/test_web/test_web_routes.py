import json

import polars as pl
import pytest
from fastapi.testclient import TestClient

from dia_run.data_models.paths import DataPaths
from dia_run.web.app import app
from dia_run.web.dependencies import get_data_paths


@pytest.fixture
def web_data_paths(
    *,
    tmp_path_factory: pytest.TempPathFactory,
    strava_summary_data: pl.DataFrame,
    carelink_data: pl.DataFrame,
    strava_stream_data: pl.DataFrame,
    questionnaire_data: dict[int, dict],
) -> DataPaths:
    root = tmp_path_factory.mktemp("web_data")
    carelink_dir = root / "web_carelink"
    strava_summary_dir = root / "web_strava" / "summary"
    strava_stream_dir = root / "web_strava" / "stream"
    questionnaire_dir = root / "web_questionnaire"

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
    for activity_id, data in questionnaire_data.items():
        with open(data_paths.questionnaire / f"{activity_id}.json", "w") as f:
            json.dump(data, f)

    return data_paths


@pytest.fixture
def client(*, web_data_paths: DataPaths) -> TestClient:
    app.dependency_overrides[get_data_paths] = lambda: web_data_paths
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health_route(*, client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dashboard_route(*, client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Training and glucose overview" in response.text


def test_questionnaire_submission(*, client: TestClient, web_data_paths: DataPaths) -> None:
    questionnaire_path = web_data_paths.questionnaire / "1002.json"
    questionnaire_path.unlink()

    response = client.post(
        "/questionnaire/1002",
        data={
            "pre_run_carbohydrates_g": "30",
            "pre_run_time_before_start_min": "-30",
            "pre_run_bolus_percentage": "70",
            "pre_run_food_type": "Energy Bar",
            "fueling_carbohydrates_g": "15",
            "fueling_time_during_run_min": "15",
            "fueling_food_type": "Energy Gel",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("/activities/1002")
    assert questionnaire_path.exists()

    with open(questionnaire_path) as f:
        saved = json.load(f)

    assert len(saved["pre_run"]) == 1
    assert len(saved["fueling_during_run"]) == 1
