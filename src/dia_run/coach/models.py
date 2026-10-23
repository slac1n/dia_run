import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from dia_run.data_models.run_types import RunType


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActivityQuery(StrictModel):
    min_distance_km: float = Field(default=0, ge=0, le=1000)
    max_distance_km: float = Field(default=1000, ge=0, le=1000)
    limit: int = Field(default=10, ge=1, le=20)
    run_type: RunType | None = None
    after: str | None = Field(default=None, max_length=10, description="Inclusive ISO date YYYY-MM-DD")
    before: str | None = Field(default=None, max_length=10, description="Exclusive ISO date YYYY-MM-DD")


class ActivityRequest(StrictModel):
    activity_id: int = Field(gt=0, strict=True)


class GlucoseRequest(ActivityRequest):
    start_min: int = Field(default=0, ge=-180, le=2880)
    end_min: int = Field(default=2880, ge=-180, le=2880)
    offset: int = Field(default=0, ge=0, le=10000)


class ComparisonRequest(ActivityRequest):
    tolerance_pct: int = Field(default=20, ge=1, le=50)
    limit: int = Field(default=5, ge=1, le=10)


class Evidence(StrictModel):
    id: str
    tool: str
    activity_ids: list[int]
    data: dict[str, Any]


class ToolFunction(StrictModel):
    name: str = Field(max_length=100)
    arguments: str = Field(max_length=4000)


class ToolCall(StrictModel):
    index: int | None = Field(default=None, ge=0, exclude=True)
    id: str = Field(min_length=1, max_length=200)
    type: Literal["function"]
    function: ToolFunction


class RunComparisonRequest(StrictModel):
    activity_ids: list[Annotated[int, Field(gt=0, strict=True)]] = Field(min_length=2, max_length=5)


class TrainingOverviewRequest(StrictModel):
    days: int = Field(default=28, ge=1, le=90)
    end_date: str | None = Field(default=None, max_length=10, description="Inclusive ISO date; defaults to today")


class MemoryQuery(StrictModel):
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=5, ge=1, le=8)


class MemoryUpdate(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,59}$")
    category: Literal["preference", "goal", "schedule", "follow_up"]
    text: str = Field(min_length=8, max_length=600)
    quote: str = Field(min_length=3, max_length=400)
    context_quote: str = Field(default="", max_length=1000)
    retention_days: int = Field(default=90, ge=1, le=180)


class MemoryForget(StrictModel):
    memory_id: str = Field(pattern=r"^M[0-9a-f]{32}$")
    quote: str = Field(min_length=3, max_length=400)


class CoachAnswer(StrictModel):
    message: str = Field(min_length=1, max_length=12000)
    memory_updates: list[MemoryUpdate] = Field(default_factory=list, max_length=3)
    forget_memories: list[MemoryForget] = Field(default_factory=list, max_length=5)

    def validate_sources(self, *, messages: list[dict[str, Any]]) -> None:
        user_index = next((i for i in range(len(messages) - 1, -1, -1) if messages[i]["role"] == "user"), -1)
        question = messages[user_index]["content"] if user_index >= 0 else ""
        if any(item.quote not in question for item in [*self.memory_updates, *self.forget_memories]):
            raise ValueError("Memory must quote the current user message exactly")
        context = []
        for message in messages[: max(user_index, 0)]:
            if message["role"] == "user":
                context.append(message["content"])
            elif message["role"] == "assistant" and not message.get("tool_calls"):
                context.append(json.loads(message["content"])["message"])
        if any(
            note.context_quote and not any(note.context_quote in text for text in context)
            for note in self.memory_updates
        ):
            raise ValueError("Memory context must quote preceding conversation text exactly")
