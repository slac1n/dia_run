from typing import Literal

FetchStatus = Literal["none", "started", "success", "error"]

_current_status: FetchStatus = "none"


def set_fetch_status(*, status: FetchStatus) -> None:
    global _current_status  # noqa: PLW0603
    _current_status = status


def get_fetch_status() -> FetchStatus:
    return _current_status
