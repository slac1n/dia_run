from fastapi.testclient import TestClient

from dia_run.web.app import app
from dia_run.web.fetch_status import get_fetch_status, set_fetch_status


class TestFetchStatusModule:
    def test_default_status_is_none(self) -> None:
        set_fetch_status(status="none")
        assert get_fetch_status() == "none"

    def test_set_and_get_started(self) -> None:
        set_fetch_status(status="started")
        assert get_fetch_status() == "started"

    def test_set_and_get_success(self) -> None:
        set_fetch_status(status="success")
        assert get_fetch_status() == "success"

    def test_set_and_get_error(self) -> None:
        set_fetch_status(status="error")
        assert get_fetch_status() == "error"


class TestQuestionnaireStatusEndpoint:
    def test_returns_current_fetch_status(self) -> None:
        set_fetch_status(status="none")
        with TestClient(app) as client:
            response = client.get("/questionnaire/status")
            assert response.status_code == 200
            assert response.json() == {"status": "none"}

    def test_returns_started_after_fetch_begins(self) -> None:
        set_fetch_status(status="started")
        with TestClient(app) as client:
            response = client.get("/questionnaire/status")
            assert response.status_code == 200
            assert response.json() == {"status": "started"}

    def test_returns_success_after_fetch_completes(self) -> None:
        set_fetch_status(status="success")
        with TestClient(app) as client:
            response = client.get("/questionnaire/status")
            assert response.status_code == 200
            assert response.json() == {"status": "success"}

    def test_returns_error_after_fetch_fails(self) -> None:
        set_fetch_status(status="error")
        with TestClient(app) as client:
            response = client.get("/questionnaire/status")
            assert response.status_code == 200
            assert response.json() == {"status": "error"}
