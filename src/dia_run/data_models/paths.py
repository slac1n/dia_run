from pathlib import Path

from pydantic import BaseModel

DEFAULT_DATA_ROOT = Path("data")


class DataPaths(BaseModel):
    data_root: Path = DEFAULT_DATA_ROOT
    strava_summary: Path = DEFAULT_DATA_ROOT / "strava" / "summary"
    strava_stream: Path = DEFAULT_DATA_ROOT / "strava" / "stream"
    carelink: Path = DEFAULT_DATA_ROOT / "carelink"
    questionnaire: Path = DEFAULT_DATA_ROOT / "run_questionnaires"

    @classmethod
    def from_root(cls, *, root: Path) -> "DataPaths":
        return cls(
            data_root=root,
            strava_summary=root / "strava" / "summary",
            strava_stream=root / "strava" / "stream",
            carelink=root / "carelink",
            questionnaire=root / "run_questionnaires",
        )
