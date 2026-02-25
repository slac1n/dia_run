from __future__ import annotations

from enum import StrEnum


class RunType(StrEnum):
    EASY = "Easy Run"
    INTERVAL = "Interval"
    TEMPO = "Tempo Run"
    LONG = "Long Run"
    RACE = "Race"
    OTHER = "Other"

    @classmethod
    def get_keyword(cls, run_type: RunType) -> str | None:
        """Get the keyword associated with a run type."""
        keywords_map = {
            cls.EASY: "Easy",
            cls.INTERVAL: "Interval",
            cls.TEMPO: "Tempo",
            cls.LONG: "Long",
            cls.RACE: None,  # Race is detected via regex pattern
            cls.OTHER: None,
        }
        return keywords_map.get(run_type)

    @classmethod
    def get_race_pattern(cls) -> str:
        """Get regex pattern for detecting race keywords in run names."""
        return r"(?i)\b(half[- ]?marathon|halbmarathon|marathon)\b"
