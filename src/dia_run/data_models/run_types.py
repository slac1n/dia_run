from __future__ import annotations

from enum import StrEnum


class RunType(StrEnum):
    EASY = "Easy Run"
    INTERVAL = "Interval"
    TEMPO = "Tempo Run"
    LONG = "Long Run"
    OTHER = "Other"

    @classmethod
    def get_keyword(cls, run_type: RunType) -> str | None:
        """Get the keyword associated with a run type."""
        keywords_map = {
            cls.EASY: "Easy",
            cls.INTERVAL: "Interval",
            cls.TEMPO: "Tempo",
            cls.LONG: "Long",
            cls.OTHER: None,
        }
        return keywords_map.get(run_type)
