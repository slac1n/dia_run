import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import polars as pl
import pytest
import requests
from fastapi.testclient import TestClient

from dia_run.coach.agent import respond
from dia_run.coach.history import ChatStore
from dia_run.coach.tools import CoachTools
from dia_run.data_models.paths import DataPaths
from dia_run.data_processing.data_processing import DataProcessor
from dia_run.llm.openrouter_client import OpenRouterError, request_tool_completion
from dia_run.settings import settings
from dia_run.web.app import create_app
from dia_run.web.dependencies import get_data_paths


@pytest.fixture
def coach_tools(*, test_data_paths: DataPaths) -> CoachTools:
    return CoachTools(processor=DataProcessor(data_paths=test_data_paths))


def _call(
    *, name: str = "find_activities", arguments: dict[str, Any] | None = None, call_id: str = "call1"
) -> dict[str, Any]:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments or {})}}


def _answer(*, refs: list[str] | None = None) -> dict[str, Any]:
    return {
        "content": json.dumps(
            {
                "message": "A run was recorded. " + " ".join(f"[{ref}]" for ref in (refs or ["E1"])),
                "memory_updates": [],
                "forget_memories": [],
            }
        )
    }


class TestCoachTools:
    def test_marathon_selection_and_allowlist(self, *, coach_tools: CoachTools) -> None:
        result = coach_tools.execute(
            name="find_activities", evidence_id="E1", arguments='{"min_distance_km":42,"max_distance_km":43}'
        )
        assert result.activity_ids == [1004]
        assert "name" not in result.data["activities"][0]
        assert result.data["activities"][0]["distance"] == 42195

    @pytest.mark.parametrize(
        "name,arguments",
        [
            ("execute_python", "{}"),
            ("get_activity_context", '{"activity_id":"../secrets"}'),
            ("get_activity_context", '{"activity_id":99999}'),
            ("find_activities", '{"limit":9999}'),
            ("find_activities", '{"path":"/tmp"}'),
            ("find_activities", '{"before":"not-a-date"}'),
            ("find_activities", '{"min_distance_km":50,"max_distance_km":10}'),
        ],
    )
    def test_rejects_invalid_tools_and_arguments(self, *, coach_tools: CoachTools, name: str, arguments: str) -> None:
        with pytest.raises(ValueError):
            coach_tools.execute(name=name, arguments=arguments, evidence_id="E1")

    def test_glucose_sorted_bounded_and_missing(
        self, *, coach_tools: CoachTools, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        start = datetime(2025, 3, 25, 10)
        samples = pl.DataFrame(
            {
                "datetime": [start + timedelta(minutes=m) for m in [20, -60, 0, 5, 40, 10]],
                "type": ["CGM"] * 6,
                "value": [80.0, 200.0, 140.0, None, 180.0, 100.0],
            }
        )
        monkeypatch.setattr(coach_tools.processor, "get_specific_carelink", lambda **_: samples)
        result = coach_tools.execute(name="get_glucose_analysis", arguments='{"activity_id":1001}', evidence_id="E1")
        metrics = result.data["metrics"]
        assert metrics["valid_samples"] == 3
        assert metrics["missing_samples"] == 1
        assert metrics["first_mg_dl"] == 140
        assert metrics["last_mg_dl"] == 80
        assert metrics["change_mg_dl"] == -60
        assert metrics["max_gap_minutes"] == 10
        assert metrics["samples_in_target_pct"] == pytest.approx(200 / 3)
        assert len(result.data["measurements"]) == 4

    def test_empty_glucose_is_not_zero(self, *, coach_tools: CoachTools, monkeypatch: pytest.MonkeyPatch) -> None:
        empty = pl.DataFrame(schema={"datetime": pl.Datetime, "type": pl.String, "value": pl.Float64})
        monkeypatch.setattr(coach_tools.processor, "get_specific_carelink", lambda **_: empty)
        result = coach_tools.execute(name="get_glucose_analysis", arguments='{"activity_id":1001}', evidence_id="E1")
        assert result.data["metrics"]["valid_samples"] == 0
        assert result.data["metrics"]["mean_mg_dl"] is None
        assert result.data["metrics"]["change_mg_dl"] is None
        assert result.data["measurements"] == []

    def test_pagination_metrics_cover_full_window(
        self, *, coach_tools: CoachTools, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        start = datetime(2025, 3, 25, 10)
        samples = pl.DataFrame(
            {
                "datetime": [start + timedelta(seconds=i) for i in range(350)],
                "type": ["CGM"] * 350,
                "value": [120.0] * 350,
            }
        )
        monkeypatch.setattr(coach_tools.processor, "get_specific_carelink", lambda **_: samples)
        first = coach_tools.execute(name="get_glucose_analysis", arguments='{"activity_id":1001}', evidence_id="E1")
        second = coach_tools.execute(
            name="get_glucose_analysis", arguments='{"activity_id":1001,"offset":300}', evidence_id="E2"
        )
        assert len(first.data["measurements"]) == 300
        assert first.data["next_offset"] == 300
        assert len(second.data["measurements"]) == 50
        assert second.data["next_offset"] is None
        assert first.data["metrics"] == second.data["metrics"]
        assert first.data["metrics"]["valid_samples"] == 350

    def test_missing_questionnaire_is_explicit(self, *, coach_tools: CoachTools, tmp_path: Path) -> None:
        coach_tools.processor.get_summary()
        coach_tools.processor.data_paths = DataPaths.from_root(root=tmp_path)
        # Reuse a preloaded summary; missing local questionnaire must not mean zero intake.
        result = coach_tools.execute(name="get_fueling_events", arguments='{"activity_id":1001}', evidence_id="E1")
        assert result.data["questionnaire_recorded"] is False
        assert result.data["during_run"] == []
        assert result.data["recorded_during_carbs_g"] == 0

    def test_fueling_totals(self, *, coach_tools: CoachTools) -> None:
        result = coach_tools.execute(name="get_fueling_events", arguments='{"activity_id":1004}', evidence_id="E1")
        assert result.data["recorded_during_carbs_g"] == 50
        assert result.data["questionnaire_recorded"] is True
        assert "food_type" not in result.data["during_run"][0]

    def test_comparison_excludes_target(self, *, coach_tools: CoachTools) -> None:
        result = coach_tools.execute(name="find_comparable_runs", arguments='{"activity_id":1004}', evidence_id="E1")
        assert result.data["activities"] == []
        assert result.data["total_matches"] == 0


class TestAgent:
    def test_multi_round_and_followup(self, *, coach_tools: CoachTools, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = Mock(
            side_effect=[
                {"tool_calls": [_call()], "reasoning_details": [{"type": "reasoning.encrypted", "data": "opaque"}]},
                {
                    "tool_calls": [
                        _call(name="get_fueling_events", arguments={"activity_id": 1004}, call_id="call2"),
                        _call(name="get_glucose_analysis", arguments={"activity_id": 1004}, call_id="call3"),
                    ]
                },
                _answer(refs=["E2", "E3"]),
                _answer(refs=["E1"]),
            ]
        )
        monkeypatch.setattr("dia_run.coach.agent.request_tool_completion", provider)
        original: list[dict[str, Any]] = []
        history = respond(messages=original, question="Last marathon?", tools=coach_tools)
        assert original == []
        assert history[1]["reasoning_details"][0]["data"] == "opaque"
        assert len([m for m in history if m["role"] == "tool"]) == 3
        followup = respond(messages=history, question="What about fueling?", tools=coach_tools)
        assert followup[: len(history)] == history
        assert len(provider.call_args.kwargs["messages"]) == len(history) + 2

    def test_unknown_citation_rejected(self, *, coach_tools: CoachTools, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("dia_run.coach.agent.request_tool_completion", Mock(return_value=_answer()))
        with pytest.raises(OpenRouterError, match="unavailable evidence"):
            respond(messages=[], question="Why?", tools=coach_tools)

    def test_invalid_tool_returns_safe_error(self, *, coach_tools: CoachTools, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = Mock(
            side_effect=[
                {"tool_calls": [_call(name="shell", arguments={"secret": "sensitive"})]},
                {"content": json.dumps({"message": "No evidence."})},
            ]
        )
        monkeypatch.setattr("dia_run.coach.agent.request_tool_completion", provider)
        history = respond(messages=[], question="Why?", tools=coach_tools)
        error = next(m["content"] for m in history if m["role"] == "tool")
        assert "Invalid query" in error
        assert "sensitive" not in error

    def test_round_and_context_limits(self, *, coach_tools: CoachTools, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = Mock(return_value={"tool_calls": [_call()]})
        monkeypatch.setattr("dia_run.coach.agent.request_tool_completion", provider)
        monkeypatch.setattr(settings, "coach_max_rounds", 2)
        with pytest.raises(OpenRouterError, match="round limit"):
            respond(messages=[], question="Why?", tools=coach_tools)
        assert provider.call_count == 2
        monkeypatch.setattr(settings, "coach_max_context_chars", 10)
        with pytest.raises(ValueError, match="context limit"):
            respond(messages=[], question="Why?", tools=coach_tools)
        assert provider.call_count == 2

    def test_unavailable_data_returns_safe_error(
        self, *, coach_tools: CoachTools, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = Mock(
            side_effect=[
                {"tool_calls": [_call()]},
                {"content": json.dumps({"message": "No data available."})},
            ]
        )
        monkeypatch.setattr("dia_run.coach.agent.request_tool_completion", provider)
        monkeypatch.setattr(coach_tools.processor, "get_summary", Mock(side_effect=FileNotFoundError("sensitive path")))
        history = respond(messages=[], question="Why?", tools=coach_tools)
        assert "sensitive path" not in json.dumps(history)
        assert "unavailable activity/data" in json.dumps(history)

    def test_call_budget(self, *, coach_tools: CoachTools, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "coach_max_tool_calls", 1)
        monkeypatch.setattr(
            "dia_run.coach.agent.request_tool_completion",
            Mock(return_value={"tool_calls": [_call(), _call(call_id="second")]}),
        )
        with pytest.raises(OpenRouterError, match="tool-call limit"):
            respond(messages=[], question="Why?", tools=coach_tools)


class TestHistory:
    def test_persistence_isolation_conflicts_deletion(self, *, tmp_path: Path) -> None:
        path = tmp_path / "private" / "chats.sqlite3"
        store = ChatStore(path=path, data_root=tmp_path / "data")
        chat = store.create(owner="alice")
        messages = [{"role": "user", "content": "Private health question"}]
        store.save(chat_id=chat, owner="alice", messages=messages, revision=0)
        reopened = ChatStore(path=path, data_root=tmp_path / "data")
        assert reopened.load(chat_id=chat, owner="alice") == (messages, 1)
        assert reopened.list_chats(owner="bob") == []
        with pytest.raises(ValueError, match="not found"):
            reopened.load(chat_id=chat, owner="bob")
        with pytest.raises(ValueError, match="changed"):
            store.save(chat_id=chat, owner="alice", messages=[], revision=0)
        store.delete(chat_id=chat, owner="bob")
        assert store.load(chat_id=chat, owner="alice")[0] == messages
        store.delete(chat_id=chat, owner="alice")
        assert store.list_chats(owner="alice") == []
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
        assert b"Private health question" not in path.read_bytes()

    def test_synced_root_forbidden(self, *, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="outside"):
            ChatStore(path=tmp_path / "data" / "chat.sqlite3", data_root=tmp_path / "data")


class TestProvider:
    def test_privacy_and_config(self, *, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "openrouter_api_key", "test-secret")
        monkeypatch.setattr(settings, "openrouter_model", "test/model")
        post = Mock(return_value=Mock(status_code=200, json=lambda: {"choices": [{"message": _answer()}]}))
        monkeypatch.setattr("dia_run.llm.openrouter_client.requests.post", post)
        request_tool_completion(messages=[], tools=[])
        payload = post.call_args.kwargs["json"]
        assert payload["model"] == "test/model"
        assert payload["provider"] == {"require_parameters": True, "data_collection": "deny", "zdr": True}

    @pytest.mark.parametrize("failure", ["http", "transport", "json", "shape"])
    def test_errors_do_not_expose_payload(self, *, monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
        monkeypatch.setattr(settings, "openrouter_api_key", "test-secret")
        response = Mock(status_code=500 if failure == "http" else 200, text="PRIVATE HEALTH DATA")
        response.json.side_effect = ValueError("PRIVATE HEALTH DATA") if failure == "json" else None
        response.json.return_value = {"error": "PRIVATE HEALTH DATA"}
        post = Mock(return_value=response)
        if failure == "transport":
            post.side_effect = requests.RequestException("PRIVATE HEALTH DATA")
        monkeypatch.setattr("dia_run.llm.openrouter_client.requests.post", post)
        with pytest.raises(OpenRouterError) as error:
            request_tool_completion(messages=[], tools=[])
        assert "PRIVATE" not in str(error.value)


class TestCoachWeb:
    def test_personal_history_survives_new_browser_session(
        self, *, tmp_path: Path, test_data_paths: DataPaths, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "coach_enabled", True)
        monkeypatch.setattr(settings, "coach_history_path", tmp_path / "private" / "chats.sqlite3")
        app = create_app()
        app.dependency_overrides[get_data_paths] = lambda: test_data_paths
        answer = json.loads(_answer()["content"])
        provider = Mock(side_effect=[{"tool_calls": [_call()]}, {"content": json.dumps(answer)}])
        monkeypatch.setattr("dia_run.coach.agent.request_tool_completion", provider)
        client = TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000))
        page = client.get("/coach")
        assert page.status_code == 200
        assert page.headers["cache-control"] == "no-store"
        token = re.search(r'name="csrf_token" value="([a-f0-9]+)"', page.text)
        assert token
        form = {"question": "<script>alert(1)</script>", "csrf_token": token[1]}
        assert client.post("/coach/message", data=form).status_code == 400
        assert provider.call_count == 0
        assert client.post("/coach/message", data={**form, "consent": "true", "csrf_token": "bad"}).status_code == 403
        response = client.post("/coach/message", data={**form, "consent": "true"})
        assert response.status_code == 200
        assert "A run was recorded." in response.text
        assert "<h2>Limitations</h2>" not in response.text
        assert "<h2>Hypotheses</h2>" not in response.text
        assert "<script>alert(1)</script>" not in response.text
        assert 'href="#E1"' in response.text
        other = TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50001))
        assert "A run was recorded." in other.get(str(response.url)).text
        assert response.url.params["chat_id"] in other.get("/coach").text
        assert (
            other.post(
                "/coach/delete", data={"chat_id": response.url.params["chat_id"], "csrf_token": token[1]}
            ).status_code
            == 403
        )
        chat_id = response.url.params["chat_id"]
        deleted = client.post("/coach/delete", data={"chat_id": chat_id, "csrf_token": token[1]})
        assert deleted.status_code == 200
        assert client.get(f"/coach?chat_id={chat_id}").status_code == 404

    @pytest.mark.parametrize("environment", ["development", "production"])
    def test_disabled_coach(self, *, environment: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "app_env", environment)
        monkeypatch.setattr(settings, "coach_enabled", False)
        client = TestClient(create_app(), base_url="http://10.44.0.1", client=("10.44.0.2", 50000))
        assert client.get("/coach").status_code == 404


def test_failed_question_survives_refresh_and_retry(
    *, tmp_path: Path, test_data_paths: DataPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coach_enabled", True)
    monkeypatch.setattr(settings, "coach_history_path", tmp_path / "private" / "chats.sqlite3")
    app = create_app()
    app.dependency_overrides[get_data_paths] = lambda: test_data_paths
    provider = Mock(side_effect=OpenRouterError("Provider returned an invalid findings format."))
    monkeypatch.setattr("dia_run.coach.agent.request_tool_completion", provider)
    client = TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000))
    page = client.get("/coach")
    token = re.search(r'name="csrf_token" value="([a-f0-9]+)"', page.text)
    assert token
    form = {"question": "My synthetic question", "csrf_token": token[1], "consent": "true"}
    failed = client.post("/coach/message", data=form)
    assert failed.status_code == 200
    assert "The coach could not finish." in failed.text
    refreshed = client.get(str(failed.url))
    assert "Provider returned an invalid findings format." in refreshed.text
    assert "My synthetic question</textarea>" in refreshed.text
    assert 'id="coach-progress"' in refreshed.text
    provider.side_effect = [{"tool_calls": [_call()]}, _answer()]
    retried = client.post("/coach/message", data={**form, "chat_id": failed.url.params["chat_id"]})
    assert "A run was recorded." in retried.text
    assert "The coach could not finish." not in retried.text
    assert "My synthetic question</textarea>" not in retried.text


def test_provider_output_limit_is_explicit(*, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    response = Mock(status_code=200)
    response.json.return_value = {"choices": [{"finish_reason": "length", "message": {"content": "{"}}]}
    monkeypatch.setattr("dia_run.llm.openrouter_client.requests.post", Mock(return_value=response))
    with pytest.raises(OpenRouterError, match="output limit"):
        request_tool_completion(messages=[], tools=[])


def test_coach_environment_settings(*, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from dia_run.settings import AppSettings

    monkeypatch.setenv("COACH_ENABLED", "true")
    monkeypatch.setenv("COACH_MAX_ROUNDS", "6")
    monkeypatch.setenv("COACH_HISTORY_PATH", str(tmp_path / "chat.sqlite3"))
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    config = AppSettings(_env_file=None)
    assert config.coach_enabled is True
    assert config.coach_max_rounds == 6
    assert config.coach_history_path == tmp_path / "chat.sqlite3"
    assert config.openrouter_model == "anthropic/claude-sonnet-5.5"
