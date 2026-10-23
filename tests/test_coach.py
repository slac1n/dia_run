"""Coach calculations and memory lifecycle, using synthetic data only."""

import json
import re
import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from dia_run.coach.agent import respond
from dia_run.coach.history import ChatStore
from dia_run.coach.models import CoachAnswer, MemoryUpdate
from dia_run.coach.tools import CoachTools, tool_definitions
from dia_run.data_models.paths import DataPaths
from dia_run.data_processing.data_processing import DataProcessor
from dia_run.llm.openrouter_client import OpenRouterError
from dia_run.settings import settings
from dia_run.web.app import create_app
from dia_run.web.dependencies import get_data_paths


@pytest.fixture
def store(*, tmp_path: Path) -> ChatStore:
    return ChatStore(path=tmp_path / "private" / "chats.sqlite3", data_root=tmp_path / "data")


def _save_note(*, store: ChatStore, quote: str, key: str = "availability", category: str = "schedule") -> str:
    chat = store.create(owner="personal")
    answer = CoachAnswer.model_validate(
        {
            "message": "Understood.",
            "memory_updates": [{"key": key, "category": category, "text": quote, "quote": quote, "retention_days": 30}],
        }
    )
    store.save(chat_id=chat, owner="personal", revision=0, messages=[{"role": "user", "content": quote}], answer=answer)
    return chat


def test_memory_restart_correction_source_and_forget(*, store: ChatStore, tmp_path: Path) -> None:
    first = _save_note(store=store, quote="I can train on Tuesdays.")
    original = store.list_memories(owner="personal")[0]
    second = _save_note(store=store, quote="I now train on Thursdays.")
    reopened = ChatStore(path=store.path, data_root=tmp_path / "data")
    notes = reopened.list_memories(owner="personal")
    assert len(notes) == 1
    assert notes[0]["id"] == original["id"]
    assert notes[0]["quote"] == "I now train on Thursdays."
    assert notes[0]["source_chat"] == second
    assert reopened.list_memories(owner="someone_else") == []
    reopened.delete(chat_id=first, owner="personal")
    assert len(reopened.list_memories(owner="personal")) == 1
    reopened.forget_memory(memory_id=notes[0]["id"], owner="someone_else")
    assert len(reopened.list_memories(owner="personal")) == 1
    reopened.forget_memory(memory_id=notes[0]["id"], owner="personal")
    assert reopened.list_memories(owner="personal") == []
    assert reopened.load(chat_id=second, owner="personal")[0]


def test_memory_source_and_atomic_conflict(*, store: ChatStore) -> None:
    chat = store.create(owner="personal")
    answer = CoachAnswer(
        message="Okay",
        memory_updates=[
            MemoryUpdate(
                key="preference", category="preference", text="I prefer morning runs.", quote="I prefer morning runs."
            )
        ],
    )
    with pytest.raises(ValueError, match="quote"):
        store.save(
            chat_id=chat, owner="personal", revision=0, messages=[{"role": "user", "content": "Hello"}], answer=answer
        )
    assert store.load(chat_id=chat, owner="personal") == ([], 0)
    with pytest.raises(ValueError, match="changed"):
        store.save(
            chat_id=chat,
            owner="personal",
            revision=99,
            messages=[{"role": "user", "content": "I prefer morning runs."}],
            answer=answer,
        )
    assert store.list_memories(owner="personal") == []


def test_memory_expiry_selection_duplicates_and_source_deletion(*, store: ChatStore) -> None:
    _save_note(store=store, quote="My goal is a trail race.", key="race", category="goal")
    _save_note(store=store, quote="My goal is a trail race.", key="duplicate", category="goal")
    assert len(store.list_memories(owner="personal")) == 1
    chat = _save_note(store=store, quote="Check how the new gels felt.", key="gels", category="follow_up")
    selected = store.search_memories(owner="personal", query="How did gels feel?")
    assert len(selected) == 1 and selected[0]["key"] == "gels"
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE memories SET expires_at='2000-01-01' WHERE key='race'")
    assert len(store.search_memories(owner="personal", query="race gels", include_context=True)) == 1
    store.delete(chat_id=chat, owner="personal")
    assert store.list_memories(owner="personal") == []


def test_memory_context_bounded_and_no_old_conversations(
    *, store: ChatStore, test_data_paths: DataPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    for i in range(9):
        _save_note(
            store=store, quote=f"I prefer morning runs on day {i}.", key=f"preference_{i}", category="preference"
        )
    old = store.create(owner="personal")
    store.save(
        chat_id=old, owner="personal", revision=0, messages=[{"role": "user", "content": "UNRELATED_OLD_CONVERSATION"}]
    )
    tools = CoachTools(processor=DataProcessor(data_paths=test_data_paths), store=store)
    provider = Mock(return_value={"content": '{"message":"You prefer morning runs [E1]."}'})
    monkeypatch.setattr("dia_run.coach.agent.request_tool_completion", provider)
    result = respond(messages=[], question="Hello", tools=tools)
    assert len(result[-1]["memory_context"]) == 5
    sent = json.dumps(provider.call_args.kwargs)
    assert "UNRELATED_OLD_CONVERSATION" not in sent
    assert "I prefer morning runs" in sent
    assert "memory_context" not in sent
    assert result[-1]["memory_context"][0]["id"] == "E1"
    followup = respond(messages=result, question="And next?", tools=tools)
    assert followup[-1]["memory_context"][0]["id"] == "E6"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "message": "Okay",
            "memory_updates": [
                {"key": "goal", "category": "goal", "text": "An invented goal", "quote": "An invented goal"}
            ],
        },
        {"message": "As remembered [M" + "a" * 32 + "]"},
        {"message": "As remembered [M and malformed]"},
        {"message": "Forgotten", "forget_memories": [{"memory_id": "M" + "a" * 32, "quote": "Forget it"}]},
    ],
)
def test_agent_rejects_invented_memory(
    *, payload: dict[str, object], test_data_paths: DataPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = Mock(return_value={"content": json.dumps(payload)})
    monkeypatch.setattr("dia_run.coach.agent.request_tool_completion", provider)
    with pytest.raises(OpenRouterError):
        respond(
            messages=[],
            question="Forget it",
            tools=CoachTools(processor=DataProcessor(data_paths=test_data_paths)),
        )


def test_comparison_and_training_math(*, test_data_paths: DataPaths) -> None:
    tools = CoachTools(processor=DataProcessor(data_paths=test_data_paths))
    comparison = tools.execute(name="compare_activities", arguments='{"activity_ids":[1001,1004]}', evidence_id="E1")
    first, second = comparison.data["runs"]
    assert second["difference_from_first"]["distance_m"] == 37195
    assert first["glucose"]["last_sample_time"].startswith("2025-03-25 10:30")
    fueling = second["fueling"]
    assert fueling["recorded_during_carbs_g_per_hour"] == fueling["recorded_during_carbs_g"] / 2.5
    overview = tools.execute(
        name="get_training_overview", arguments='{"days":2,"end_date":"2025-03-28"}', evidence_id="E2"
    )
    assert overview.data["current"]["recorded_runs"] == 2
    assert overview.data["current"]["distance_km"] == pytest.approx(62.195)
    assert overview.data["previous"]["distance_km"] == 13
    assert overview.data["distance_change_km"] == pytest.approx(49.195)
    empty = tools.execute(
        name="get_training_overview", arguments='{"days":1,"end_date":"2020-01-01"}', evidence_id="E3"
    )
    assert empty.data["current"]["longest_run_km"] is None
    assert empty.data["current"]["distance_km"] == 0
    with pytest.raises(ValueError):
        tools.execute(name="compare_activities", arguments='{"activity_ids":[1001,1001]}', evidence_id="E4")


def test_absent_fueling_counts_as_zero(*, test_data_paths: DataPaths, tmp_path: Path) -> None:
    processor = DataProcessor(data_paths=test_data_paths)
    processor.get_summary()
    processor.data_paths = DataPaths.from_root(root=tmp_path / "absent")
    result = CoachTools(processor=processor).execute(
        name="get_fueling_events", arguments='{"activity_id":1001}', evidence_id="E1"
    )
    assert result.data["recorded_pre_run_carbs_g"] == 0
    assert result.data["recorded_during_carbs_g_per_hour"] == 0


def test_web_auto_memory_and_forget(
    *, store: ChatStore, test_data_paths: DataPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coach_enabled", True)
    monkeypatch.setattr(settings, "coach_history_path", store.path)
    app = create_app()
    app.dependency_overrides[get_data_paths] = lambda: test_data_paths
    quote = "I prefer morning runs."
    answer = CoachAnswer(
        message="We can work with that.",
        memory_updates=[MemoryUpdate(key="time_preference", category="preference", text=quote, quote=quote)],
    )
    provider = Mock(return_value={"content": answer.model_dump_json()})
    monkeypatch.setattr("dia_run.coach.agent.request_tool_completion", provider)
    client = TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000))
    page = client.get("/coach")
    token = re.search(r'name="csrf_token" value="([a-f0-9]+)"', page.text)
    assert token
    response = client.post("/coach/message", data={"question": quote, "csrf_token": token[1], "consent": "true"})
    assert "We can work with that." in response.text
    notes = store.list_memories(owner="personal")
    assert len(notes) == 1
    assert "Notes saved with this reply" in response.text
    assert client.post("/coach/forget", data={"memory_id": notes[0]["id"], "csrf_token": "wrong"}).status_code == 403
    assert client.post("/coach/forget", data={"memory_id": notes[0]["id"], "csrf_token": token[1]}).status_code == 200
    assert store.list_memories(owner="personal") == []


def test_conversational_forget_uses_memory_tool_without_loading_runs(
    *, store: ChatStore, test_data_paths: DataPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_note(store=store, quote="Check how the new gels felt.", key="gels", category="follow_up")
    note = store.list_memories(owner="personal")[0]
    processor = DataProcessor(data_paths=test_data_paths)
    monkeypatch.setattr(processor, "get_summary", Mock(side_effect=AssertionError("Memory needs no activity data")))
    provider = Mock(
        side_effect=[
            {
                "tool_calls": [
                    {
                        "id": "memory1",
                        "type": "function",
                        "function": {"name": "search_memory", "arguments": '{"query":"gels"}'},
                    }
                ]
            },
            {
                "content": json.dumps(
                    {
                        "message": "I've removed that note.",
                        "forget_memories": [{"memory_id": note["id"], "quote": "Forget the gels follow-up"}],
                    }
                )
            },
        ]
    )
    monkeypatch.setattr("dia_run.coach.agent.request_tool_completion", provider)
    history = respond(
        messages=[], question="Forget the gels follow-up", tools=CoachTools(processor=processor, store=store)
    )
    assert json.loads(history[2]["content"])["data"]["active_note_count"] == 1
    # Model proposals alone never mutate the store.
    assert len(store.list_memories(owner="personal")) == 1
    chat = store.create(owner="personal")
    store.save(
        chat_id=chat,
        owner="personal",
        revision=0,
        messages=history,
        answer=CoachAnswer.model_validate_json(history[-1]["content"]),
    )
    assert store.list_memories(owner="personal") == []


def test_fueling_rate_excludes_after_finish(*, test_data_paths: DataPaths, monkeypatch: pytest.MonkeyPatch) -> None:
    from dia_run.data_models.questionnaire import FuelingEntry, QuestionnaireModel

    processor = DataProcessor(data_paths=test_data_paths)
    processor.get_summary()
    questionnaire = QuestionnaireModel(
        fueling_during_run=[
            FuelingEntry(carbohydrates_g=20, time_during_run_min=15, food_type="gel"),
            FuelingEntry(carbohydrates_g=40, time_during_run_min=31, food_type="gel"),
        ]
    )
    monkeypatch.setattr(processor, "get_questionnaire", Mock(return_value=questionnaire))
    result = CoachTools(processor=processor).execute(
        name="get_fueling_events", arguments='{"activity_id":1001}', evidence_id="E1"
    )
    assert result.data["recorded_during_carbs_g"] == 20
    assert result.data["recorded_during_carbs_g_per_hour"] == 40
    assert result.data["excluded_after_finish_entries"] == 1


def test_empty_memory_search_is_not_offered() -> None:
    assert "search_memory" not in {item["function"]["name"] for item in tool_definitions(include_memory=False)}
    assert len(tool_definitions(include_memory=False)) == 7


@pytest.mark.parametrize(
    "content",
    [
        '```json\n{"message":"What would you like to improve?"}\n```',
        '```\n{"message":"What would you like to improve?"}\n```',
    ],
)
def test_fenced_answer_is_validated_without_another_call(
    *, content: str, test_data_paths: DataPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = Mock(return_value={"content": content})
    monkeypatch.setattr("dia_run.coach.agent.request_tool_completion", provider)
    history = respond(
        messages=[],
        question="For my next marathon what could I change?",
        tools=CoachTools(processor=DataProcessor(data_paths=test_data_paths)),
    )
    assert CoachAnswer.model_validate_json(history[-1]["content"]).message == "What would you like to improve?"
    assert provider.call_count == 1


@pytest.mark.parametrize("invalid", ["A plain prose reply", '{"answer":"Wrong field"}', '{"message":', None])
def test_reply_format_repaired_once_without_polluting_history(
    *, invalid: str | None, test_data_paths: DataPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = Mock(side_effect=[{"content": invalid}, {"content": '{"message":"What is your goal?"}'}])
    monkeypatch.setattr("dia_run.coach.agent.request_tool_completion", provider)
    history = respond(
        messages=[],
        question="For my next marathon what could I change?",
        tools=CoachTools(processor=DataProcessor(data_paths=test_data_paths)),
    )
    assert len(history) == 2
    assert provider.call_count == 2
    assert provider.call_args.kwargs["tools"] == []
    assert CoachAnswer.model_validate_json(history[-1]["content"]).message == "What is your goal?"


@pytest.mark.parametrize(
    "repaired,error",
    [
        ({"content": "Still invalid"}, "after an automatic retry"),
        ({"content": '{"message":"A claim [E999]"}'}, "unavailable evidence"),
        (
            {
                "content": json.dumps(
                    {
                        "message": "Okay",
                        "memory_updates": [
                            {"key": "goal", "category": "goal", "text": "invented goal", "quote": "invented goal"}
                        ],
                    }
                )
            },
            "exact user source",
        ),
        ({"tool_calls": [{"id": "anything"}]}, "instead of the repaired reply"),
    ],
)
def test_format_repair_stays_bounded_and_preserves_safeguards(
    *, repaired: dict[str, object], error: str, test_data_paths: DataPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = Mock(side_effect=[{"content": "Invalid"}, repaired])
    monkeypatch.setattr("dia_run.coach.agent.request_tool_completion", provider)
    with pytest.raises(OpenRouterError, match=error):
        respond(
            messages=[],
            question="For my next marathon what could I change?",
            tools=CoachTools(processor=DataProcessor(data_paths=test_data_paths)),
        )
    assert provider.call_count == 2


def test_format_repair_client_omits_tool_selection(*, monkeypatch: pytest.MonkeyPatch) -> None:
    from dia_run.llm.openrouter_client import request_tool_completion

    request = Mock(return_value={"content": '{"message":"Ready"}'})
    monkeypatch.setattr("dia_run.llm.openrouter_client._request_message", request)
    request_tool_completion(messages=[], tools=[])
    assert "tools" not in request.call_args.kwargs["payload"]
    assert "tool_choice" not in request.call_args.kwargs["payload"]


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, "0 minutes"),
        (45, "less than 1 minute"),
        (60, "1 minute"),
        (2700, "45 minutes"),
        (3599, "about 60 minutes"),
        (3600, "1 hour"),
        (3660, "1 hour 1 minute"),
        (9000, "2 hours 30 minutes"),
        (9040, "about 2 hours 31 minutes"),
        (7199, "about 2 hours"),
    ],
)
def test_coach_duration_labels(*, seconds: int, expected: str) -> None:
    from dia_run.coach.tools import _duration

    assert _duration(seconds) == expected


def test_duration_labels_in_activity_and_comparison_tools(*, test_data_paths: DataPaths) -> None:
    tools = CoachTools(processor=DataProcessor(data_paths=test_data_paths))
    result = tools.execute(name="get_activity_context", arguments='{"activity_id":1004}', evidence_id="E1")
    assert result.data["activity"]["elapsed_time_display"] == "2 hours 30 minutes"
    assert result.data["activity"]["elapsed_time"] == 9000
    comparison = tools.execute(name="compare_activities", arguments='{"activity_ids":[1004,1001]}', evidence_id="E2")
    assert comparison.data["runs"][1]["activity"]["moving_time_display"] == "30 minutes"
    assert comparison.data["runs"][1]["elapsed_difference_display"] == "2 hours shorter"
    assert comparison.data["runs"][0]["elapsed_difference_display"] == "same duration"


def test_contextual_memory_retains_marathon_goal(
    *, store: ChatStore, test_data_paths: DataPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    question = "What was your goal for the Berlin marathon?"
    quote = "my goal was 3:45h"
    text = "The user's goal for the Berlin marathon was 3:45h."
    answer = CoachAnswer(
        message="Understood.",
        memory_updates=[
            MemoryUpdate(key="berlin_marathon_goal", category="goal", text=text, quote=quote, context_quote=question)
        ],
    )
    provider = Mock(return_value={"content": answer.model_dump_json()})
    monkeypatch.setattr("dia_run.coach.agent.request_tool_completion", provider)
    history = respond(
        messages=[{"role": "assistant", "content": CoachAnswer(message=question).model_dump_json()}],
        question=quote,
        tools=CoachTools(processor=DataProcessor(data_paths=test_data_paths), store=store),
    )
    chat = store.create(owner="personal")
    store.save(chat_id=chat, owner="personal", revision=0, messages=history, answer=answer)
    note = store.search_memories(owner="personal", query="Berlin marathon")[0]
    assert note["text"] == text
    assert note["quote"] == quote
    assert note["context_quote"] == question
    provider.return_value = {"content": '{"message":"Your Berlin marathon goal was 3:45h [E1]."}'}
    respond(
        messages=[],
        question="What was my race goal?",
        tools=CoachTools(processor=DataProcessor(data_paths=test_data_paths), store=store),
    )
    assert text in json.dumps(provider.call_args.kwargs["messages"])


def test_memory_rejects_fabricated_context(*, store: ChatStore) -> None:
    answer = CoachAnswer(
        message="Okay",
        memory_updates=[
            MemoryUpdate(
                key="race_goal",
                category="goal",
                text="The user's marathon goal was 3:45h.",
                quote="my goal was 3:45h",
                context_quote="What was your marathon goal?",
            )
        ],
    )
    chat = store.create(owner="personal")
    with pytest.raises(ValueError, match="context"):
        store.save(
            chat_id=chat,
            owner="personal",
            revision=0,
            messages=[{"role": "user", "content": "my goal was 3:45h"}],
            answer=answer,
        )
    assert store.list_memories(owner="personal") == []
    assert store.load(chat_id=chat, owner="personal") == ([], 0)
