from typing import Literal, TypedDict

FetchStatus = Literal["none", "started", "success", "error"]


class FetchState(TypedDict):
    status: FetchStatus
    inserted_count: int


_current_status: FetchState = {"status": "none", "inserted_count": 0}


def set_fetch_status(*, status: FetchStatus, inserted_count: int = 0) -> None:
    global _current_status  # noqa: PLW0603
    _current_status = {"status": status, "inserted_count": inserted_count}


def get_fetch_status() -> FetchState:
    return {"status": _current_status["status"], "inserted_count": _current_status["inserted_count"]}
