import json
from collections.abc import Generator
from unittest.mock import MagicMock
from urllib.parse import quote

import polars as pl
import pytest
from fastapi.testclient import TestClient

from dia_run.data_fetcher.exceptions import CareLinkDataStaleError
from dia_run.data_models.paths import DataPaths
from dia_run.web.app import app
from dia_run.web.dependencies import get_data_fetcher_service, get_data_paths, get_s3_sync_service
from dia_run.web.fetch_status import set_fetch_status
from dia_run.web.services.overview_page import get_overview_page_service


class StubFetcher:
    def __init__(self, *, new_activity_found: bool) -> None:
        self.new_activity_found = new_activity_found

    def fetch_latest_data_and_save(self) -> bool:
        return self.new_activity_found


class StaleFetcher:
    def fetch_latest_data_and_save(self) -> bool:
        raise CareLinkDataStaleError("CareLink data is out of date. Please retry later.")


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
def client(*, web_data_paths: DataPaths) -> Generator[TestClient, None, None]:
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


def test_activities_list_shows_glucose_columns(*, client: TestClient) -> None:
    response = client.get("/activities")
    assert response.status_code == 200
    assert "Avg Glucose" in response.text
    assert "TIR" in response.text
    assert "mg/dL" in response.text


def test_activity_detail_shows_glucose_tiles(*, client: TestClient) -> None:
    response = client.get("/activities/1001")
    assert response.status_code == 200
    assert "Avg Glucose" in response.text
    assert "TIR" in response.text


def test_activity_detail_shows_ai_recommendations_button(*, client: TestClient) -> None:
    response = client.get("/activities/1001")
    assert response.status_code == 200
    assert "AI recommendations" in response.text
    assert 'action="/activities/1001/recommendation"' in response.text


def test_activity_recommendation_renders_response_at_top(
    *, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _stub(*, run_context: str) -> str:  # noqa: ARG001
        return "1. Do X at T-30.\n\n2. Do Y.\n\n3. Do Z."

    monkeypatch.setattr("dia_run.web.routes.activities.request_recommendation", _stub)

    response = client.post("/activities/1001/recommendation")

    assert response.status_code == 200
    body = response.text
    assert "1. Do X at T-30." in body
    assert body.index("1. Do X at T-30.") < body.index("Back to activities")


def test_activity_recommendation_htmx_returns_fragment_only(
    *, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _stub(*, run_context: str) -> str:  # noqa: ARG001
        return "1. Do X at T-30."

    monkeypatch.setattr("dia_run.web.routes.activities.request_recommendation", _stub)

    response = client.post("/activities/1001/recommendation", headers={"HX-Request": "true"})

    assert response.status_code == 200
    body = response.text
    assert "1. Do X at T-30." in body
    assert "Back to activities" not in body
    assert "<main" not in body


def test_activity_recommendation_renders_error_when_api_fails(
    *, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dia_run.llm.openrouter_client import OpenRouterError

    def _raise(*, run_context: str) -> str:  # noqa: ARG001
        raise OpenRouterError("OPENROUTER_API_KEY is not configured.")

    monkeypatch.setattr("dia_run.web.routes.activities.request_recommendation", _raise)

    response = client.post("/activities/1001/recommendation")

    assert response.status_code == 200
    assert "Could not generate recommendations" in response.text
    assert "OPENROUTER_API_KEY is not configured." in response.text


def test_dashboard_route_uses_cached_overview_context(*, client: TestClient, web_data_paths: DataPaths) -> None:
    service = get_overview_page_service(data_paths=web_data_paths)
    service.invalidate()

    first_response = client.get("/")
    second_response = client.get("/")

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.text == second_response.text


def test_dashboard_route_cache_invalidates_after_questionnaire_submit(
    *, client: TestClient, web_data_paths: DataPaths
) -> None:
    service = get_overview_page_service(data_paths=web_data_paths)
    service.invalidate()

    questionnaire_path = web_data_paths.questionnaire / "1002.json"
    questionnaire_path.unlink(missing_ok=True)
    service.invalidate()

    initial_response = client.get("/")
    assert "You have 1 activity waiting" in initial_response.text

    response = client.post(
        "/questionnaire/1002",
        data={
            "pre_run_carbohydrates_g": "30",
            "pre_run_time_before_start_min": "-30",
            "pre_run_bolus_percentage": "70",
            "pre_run_food_type": "Energy Bar",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303

    refreshed_response = client.get("/")
    assert refreshed_response.status_code == 200
    assert "You have 1 activity waiting" not in refreshed_response.text


def test_dashboard_route_shows_fetch_success_message(*, client: TestClient) -> None:
    response = client.get(f"/?fetch=success&message={quote('Fresh data arrived')}")

    assert response.status_code == 200
    assert "Fresh data arrived" in response.text


def test_questionnaire_route_shows_new_data_banner(*, client: TestClient) -> None:
    response = client.get("/questionnaire?fetch=success")

    assert response.status_code == 200
    assert "New data downloaded! Please fill out the questionnaire for your new run(s)." in response.text


def test_questionnaire_route_shows_neutral_message_when_no_new_activities_found(*, client: TestClient) -> None:
    response = client.get("/questionnaire?fetch=no-new")

    assert response.status_code == 200
    assert "Data checked. No new activities found." in response.text
    assert "New data downloaded! Please fill out the questionnaire for your new run(s)." not in response.text


def test_questionnaire_route_shows_stale_carelink_message(*, client: TestClient) -> None:
    response = client.get("/questionnaire?fetch=stale")

    assert response.status_code == 200
    assert "CareLink data is out of date. Please retry later." in response.text


def test_fetch_route_records_inserted_activity_count(*, client: TestClient) -> None:
    sync_service = MagicMock()
    set_fetch_status(status="none")
    app.dependency_overrides[get_data_fetcher_service] = lambda: StubFetcher(new_activity_found=True)
    app.dependency_overrides[get_s3_sync_service] = lambda: sync_service

    try:
        response = client.post("/fetch", follow_redirects=False)
        status_response = client.get("/questionnaire/status")
    finally:
        app.dependency_overrides.pop(get_data_fetcher_service, None)
        app.dependency_overrides.pop(get_s3_sync_service, None)
        set_fetch_status(status="none")

    assert response.status_code == 303
    assert status_response.status_code == 200
    assert status_response.json() == {"status": "success", "new_activity_found": True}
    sync_service.sync_to_s3_after_fetch.assert_called_once_with()


def test_fetch_route_records_zero_inserted_activities(*, client: TestClient) -> None:
    sync_service = MagicMock()
    set_fetch_status(status="none")
    app.dependency_overrides[get_data_fetcher_service] = lambda: StubFetcher(new_activity_found=False)
    app.dependency_overrides[get_s3_sync_service] = lambda: sync_service

    try:
        response = client.post("/fetch", follow_redirects=False)
        status_response = client.get("/questionnaire/status")
    finally:
        app.dependency_overrides.pop(get_data_fetcher_service, None)
        app.dependency_overrides.pop(get_s3_sync_service, None)
        set_fetch_status(status="none")

    assert response.status_code == 303
    assert status_response.status_code == 200
    assert status_response.json() == {"status": "success", "new_activity_found": False}
    sync_service.sync_to_s3_after_fetch.assert_called_once_with()


def test_fetch_route_records_stale_carelink_status(*, client: TestClient) -> None:
    sync_service = MagicMock()
    set_fetch_status(status="none")
    app.dependency_overrides[get_data_fetcher_service] = lambda: StaleFetcher()
    app.dependency_overrides[get_s3_sync_service] = lambda: sync_service

    try:
        response = client.post("/fetch", follow_redirects=False)
        status_response = client.get("/questionnaire/status")
    finally:
        app.dependency_overrides.pop(get_data_fetcher_service, None)
        app.dependency_overrides.pop(get_s3_sync_service, None)
        set_fetch_status(status="none")

    assert response.status_code == 303
    assert status_response.status_code == 200
    assert status_response.json() == {"status": "stale", "new_activity_found": False}
    sync_service.sync_to_s3_after_fetch.assert_not_called()


def test_questionnaire_submission(*, client: TestClient, web_data_paths: DataPaths) -> None:
    questionnaire_path = web_data_paths.questionnaire / "1002.json"
    questionnaire_path.unlink(missing_ok=True)

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


def test_questionnaire_submission_triggers_s3_sync(*, client: TestClient, web_data_paths: DataPaths) -> None:
    questionnaire_path = web_data_paths.questionnaire / "1002.json"
    questionnaire_path.unlink(missing_ok=True)
    sync_service = MagicMock()
    app.dependency_overrides[get_s3_sync_service] = lambda: sync_service

    try:
        response = client.post(
            "/questionnaire/1002",
            data={
                "pre_run_carbohydrates_g": "30",
                "pre_run_time_before_start_min": "-30",
                "pre_run_bolus_percentage": "70",
                "pre_run_food_type": "Energy Bar",
            },
            follow_redirects=False,
        )
    finally:
        app.dependency_overrides.pop(get_s3_sync_service, None)

    assert response.status_code == 303
    sync_service.sync_to_s3_after_questionnaire.assert_called_once_with()
