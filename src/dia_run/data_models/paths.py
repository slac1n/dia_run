from pathlib import Path

from pydantic import BaseModel


class DataPaths(BaseModel):
    strava_summary: Path = Path("data") / "strava" / "summary"
    strava_stream: Path = Path("data") / "strava" / "stream"
    carelink: Path = Path("data") / "carelink"
    questionnaire: Path = Path("data") / "run_questionnaires"
