from typing import Literal, TypedDict

FetchStatus = Literal["none", "started", "success", "error", "stale"]


class FetchState(TypedDict):
    status: FetchStatus
    new_activity_found: bool


_current_status: FetchState = {"status": "none", "new_activity_found": False}


def set_fetch_status(*, status: FetchStatus, new_activity_found: bool = False) -> None:
    global _current_status  # noqa: PLW0603
    _current_status = {"status": status, "new_activity_found": new_activity_found}


def get_fetch_status() -> FetchState:
    return {"status": _current_status["status"], "new_activity_found": _current_status["new_activity_found"]}
