"""Allowlisted analysis tools. No model-supplied code or paths are executed."""

import json
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

from dia_run.coach.history import ChatStore
from dia_run.coach.models import (
    ActivityQuery,
    ActivityRequest,
    ComparisonRequest,
    Evidence,
    GlucoseRequest,
    MemoryQuery,
    RunComparisonRequest,
    TrainingOverviewRequest,
)
from dia_run.data_models.constants import TARGET_GLUCOSE_LOWER, TARGET_GLUCOSE_UPPER
from dia_run.data_processing.data_processing import DataProcessor
from dia_run.settings import settings

TOOL_MODELS = {
    "search_memory": MemoryQuery,
    "compare_activities": RunComparisonRequest,
    "get_training_overview": TrainingOverviewRequest,
    "find_activities": ActivityQuery,
    "get_activity_context": ActivityRequest,
    "get_glucose_analysis": GlucoseRequest,
    "get_fueling_events": ActivityRequest,
    "find_comparable_runs": ComparisonRequest,
}
DESCRIPTIONS = {
    "search_memory": (
        "Search contextual user notes by keyword overlap. Try concrete keywords. Returns active notes "
        "with source and expiry, not verified measurements. No writes."
    ),
    "compare_activities": (
        "Compare 2–5 distinct selected activity IDs side by side: summaries, recorded fueling "
        "totals/rates and run-window glucose metrics. Python computes differences from the first "
        "activity. Absent event entries count as zero; comparisons do not establish causality."
    ),
    "get_training_overview": (
        "Summarize recorded running over 1–90 days ending on an inclusive date (today by default), "
        "and the preceding equal-length period. Python computes counts, distance, duration, longest "
        "run and distance change."
    ),
    "find_activities": (
        "Search local activity summaries by distance in km, run type, and optional date bounds "
        "(after inclusive, before exclusive). Returns newest first, up to 20 activities, and total match count. "
        "Includes IDs, timestamps, distance, duration, average heart rate, elevation and units."
    ),
    "get_activity_context": (
        "Retrieve one activity's summary, questionnaire availability, recorded boluses and basal adjustments, "
        "and a modeled insulin estimate with its calculation method."
    ),
    "get_glucose_analysis": (
        "Retrieve sorted CGM measurements and Python-calculated statistics for one activity and time window. "
        "Times in the arguments are minutes relative to run start. Defaults to start through finish +5 min; "
        "earliest available time is -180 min. Returns first/last values, change, minimum and its time, mean, "
        "sample percentage in target, null-sample count and largest observed gap. Measurements are paginated "
        "in pages of 300 using offset/next_offset; statistics cover the full requested window."
    ),
    "get_fueling_events": (
        "Retrieve questionnaire availability, recorded pre-run carbohydrate entries with timing and bolus percentage, "
        "and during-run carbohydrate entries with timing. Includes the Python-calculated total of recorded "
        "pre-run and during-run carbs and during-run grams per elapsed hour. Food names are omitted."
    ),
    "find_comparable_runs": (
        "Find other activities of the same run type whose distance and elapsed duration are both within "
        "tolerance_pct of the selected activity (default 20%). Rank by summed relative distance and duration "
        "difference. Returns summaries, total match count and criteria; no glucose or fueling comparison."
    ),
}


def tool_definitions(*, include_memory: bool = True) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {"name": name, "description": DESCRIPTIONS[name], "parameters": model.model_json_schema()},
        }
        for name, model in TOOL_MODELS.items()
        if include_memory or name != "search_memory"
    ]


def _duration(seconds: float) -> str:
    """Format elapsed seconds at minute precision, marking rounded durations."""
    if seconds == 0:
        return "0 minutes"
    if seconds < 60:
        return "less than 1 minute"
    minutes = int(seconds / 60 + 0.5)
    hours, remaining = divmod(minutes, 60)
    if seconds < 3600:
        label = f"{minutes} minute{'s' if minutes != 1 else ''}"
    else:
        label = f"{hours} hour{'s' if hours != 1 else ''}"
        if remaining:
            label += f" {remaining} minute{'s' if remaining != 1 else ''}"
    return ("about " if seconds % 60 else "") + label


def _activity(row: dict[str, Any]) -> dict[str, Any]:
    # Explicit allowlist: no names, GPS, or device/account identifiers.
    keys = (
        "activity_id",
        "start_date_local",
        "end_date_local",
        "distance",
        "moving_time",
        "elapsed_time",
        "run_type",
        "average_heartrate",
        "total_elevation_gain",
    )
    return {
        **{key: row[key] for key in keys},
        "moving_time_display": _duration(row["moving_time"]),
        "elapsed_time_display": _duration(row["elapsed_time"]),
        "units": {
            "distance": "m",
            "moving_time": "s",
            "elapsed_time": "s",
            "average_heartrate": "bpm",
            "total_elevation_gain": "m",
        },
    }


class CoachTools:
    def __init__(self, *, processor: DataProcessor, store: ChatStore | None = None, owner: str = "personal") -> None:
        self.processor = processor
        self.store = store
        self.owner = owner

    def memory_count(self) -> int:
        return len(self.store.list_memories(owner=self.owner)) if self.store else 0

    def memory_context(self, *, query: str) -> list[dict[str, str]]:
        if self.store is None:
            return []
        return [
            {key: value for key, value in note.items() if key != "owner"}
            for note in self.store.search_memories(owner=self.owner, query=query, include_context=True)
        ]

    def execute(self, *, name: str, arguments: str, evidence_id: str) -> Evidence:
        if name not in TOOL_MODELS:
            raise ValueError("Unknown tool")
        args = TOOL_MODELS[name].model_validate_json(arguments)
        if isinstance(args, MemoryQuery):
            notes = (
                []
                if self.store is None
                else self.store.search_memories(owner=self.owner, query=args.query, limit=args.limit)
            )
            return Evidence(
                id=evidence_id,
                tool=name,
                activity_ids=[],
                data={
                    "active_note_count": self.memory_count(),
                    "user_reported_notes": [
                        {key: value for key, value in note.items() if key != "owner"} for note in notes
                    ],
                },
            )
        summary = self.processor.get_summary()
        ids: list[int] = []
        data: dict[str, Any]
        if isinstance(args, TrainingOverviewRequest):
            end = (
                date.fromisoformat(args.end_date)
                if args.end_date
                else datetime.now(ZoneInfo(settings.server_timezone)).date()
            )
            start = end - timedelta(days=args.days - 1)
            periods = []
            for first, last in ((start, end), (start - timedelta(days=args.days), start - timedelta(days=1))):
                frame = summary.filter(pl.col("start_date_local").dt.date().is_between(first, last))
                ids.extend(frame["activity_id"].to_list())
                periods.append(
                    {
                        "start_date": first,
                        "end_date": last,
                        "recorded_runs": len(frame),
                        "distance_km": frame["distance"].sum() / 1000,
                        "moving_hours": frame["moving_time"].sum() / 3600,
                        "moving_time_display": _duration(frame["moving_time"].sum()),
                        "longest_run_km": frame["distance"].max() / 1000 if len(frame) else None,
                    }
                )
            data = {
                "current": periods[0],
                "previous": periods[1],
                "distance_change_km": periods[0]["distance_km"] - periods[1]["distance_km"],
                "coverage": "Successfully loaded activity log; dates are inclusive.",
            }
        elif isinstance(args, RunComparisonRequest):
            if len(set(args.activity_ids)) != len(args.activity_ids) or any(aid <= 0 for aid in args.activity_ids):
                raise ValueError("Select distinct positive activity IDs")
            runs: list[dict[str, Any]] = []
            for aid in args.activity_ids:
                match = summary.filter(pl.col("activity_id") == aid)
                if match.is_empty():
                    raise ValueError("Activity not found")
                run = match.row(0, named=True)
                glucose = self._glucose(args=GlucoseRequest(activity_id=aid), run=run, run_only=True)
                fueling = self._fueling(run=run)
                metrics = {
                    "distance_m": run["distance"],
                    "elapsed_seconds": run["elapsed_time"],
                    **{
                        key: glucose["metrics"][key]
                        for key in ("mean_mg_dl", "min_mg_dl", "change_mg_dl", "samples_in_target_pct")
                    },
                    **{
                        key: fueling[key]
                        for key in (
                            "recorded_pre_run_carbs_g",
                            "recorded_during_carbs_g",
                            "recorded_during_carbs_g_per_hour",
                        )
                    },
                }
                baseline = runs[0]["metrics"] if runs else metrics
                differences = {
                    key: value - baseline[key] if value is not None and baseline[key] is not None else None
                    for key, value in metrics.items()
                }
                elapsed_difference: float = run["elapsed_time"] - baseline["elapsed_seconds"]
                runs.append(
                    {
                        "activity": _activity(run),
                        "fueling": fueling,
                        "glucose": glucose["metrics"],
                        "metrics": metrics,
                        "difference_from_first": differences,
                        "elapsed_difference_display": (
                            _duration(abs(elapsed_difference)) + (" longer" if elapsed_difference > 0 else " shorter")
                            if elapsed_difference != 0
                            else "same duration"
                        ),
                    }
                )
            ids = args.activity_ids
            data = {
                "runs": runs,
                "limitation": (
                    "Glucose covers start through finish; sample percentages are not time-weighted. "
                    "Differences are associations, not causal effects."
                ),
            }
        elif isinstance(args, ActivityQuery):
            if args.min_distance_km > args.max_distance_km:
                raise ValueError("Minimum distance exceeds maximum")
            matches = summary.filter(
                pl.col("distance").is_between(args.min_distance_km * 1000, args.max_distance_km * 1000)
            )
            if args.run_type:
                matches = matches.filter(pl.col("run_type") == args.run_type.value)
            if args.after:
                matches = matches.filter(pl.col("start_date_local").dt.date() >= date.fromisoformat(args.after))
            if args.before:
                matches = matches.filter(pl.col("start_date_local").dt.date() < date.fromisoformat(args.before))
            rows = matches.sort("start_date_local", descending=True).head(args.limit).to_dicts()
            ids = [row["activity_id"] for row in rows]
            data = {"activities": [_activity(row) for row in rows], "total_matches": len(matches)}
        else:
            match = summary.filter(pl.col("activity_id") == args.activity_id)
            if match.is_empty():
                raise ValueError("Activity not found")
            run = match.row(0, named=True)
            ids = [args.activity_id]
            if isinstance(args, GlucoseRequest):
                data = self._glucose(args=args, run=run)
            elif isinstance(args, ComparisonRequest):
                tolerance = args.tolerance_pct / 100
                matches = (
                    summary.filter(
                        (pl.col("activity_id") != args.activity_id)
                        & (pl.col("run_type") == run["run_type"])
                        & pl.col("distance").is_between(
                            run["distance"] * (1 - tolerance), run["distance"] * (1 + tolerance)
                        )
                        & pl.col("elapsed_time").is_between(
                            run["elapsed_time"] * (1 - tolerance), run["elapsed_time"] * (1 + tolerance)
                        )
                    )
                    .with_columns(
                        (
                            (pl.col("distance") - run["distance"]).abs() / max(run["distance"], 1)
                            + (pl.col("elapsed_time") - run["elapsed_time"]).abs() / max(run["elapsed_time"], 1)
                        ).alias("difference")
                    )
                    .sort(["difference", "activity_id"])
                )
                rows = matches.head(args.limit).to_dicts()
                ids += [row["activity_id"] for row in rows]
                data = {
                    "activities": [_activity(row) for row in rows],
                    "total_matches": len(matches),
                    "criteria": {"same_run_type": True, "distance_and_elapsed_tolerance_pct": args.tolerance_pct},
                    "limitation": "Matching does not control weather, fitness, insulin or starting glucose.",
                }
            else:
                questionnaire = self.processor.get_questionnaire(args.activity_id)
                recorded = (self.processor.data_paths.questionnaire / f"{args.activity_id}.json").is_file()
                if name == "get_fueling_events":
                    data = self._fueling(run=run)
                else:
                    data = {
                        "activity": _activity(run),
                        "questionnaire_recorded": recorded,
                        "bolus": [e.model_dump() for e in questionnaire.bolus],
                        "basal_adjustments": [e.model_dump() for e in questionnaire.basal_adjustments],
                        "estimated_insulin_units": run["insulin_on_board_in_going"],
                        "insulin_method": "Linear decay over 180 min, includes deliveries through start +5 min; "
                        "not measured IOB or a dosing calculation.",
                    }
        # Normalize dates and reject non-finite numbers before anything reaches a model or history.
        normalized = json.loads(json.dumps(data, default=str, allow_nan=False))
        if len(json.dumps(normalized)) > 60000:
            raise ValueError("Result too large; narrow the query")
        return Evidence(id=evidence_id, tool=name, activity_ids=ids, data=normalized)

    def _fueling(self, *, run: dict[str, Any]) -> dict[str, Any]:
        aid = run["activity_id"]
        questionnaire = self.processor.get_questionnaire(aid)
        recorded = (self.processor.data_paths.questionnaire / f"{aid}.json").is_file()
        entries = questionnaire.fueling_during_run
        in_run = [e for e in entries if e.time_during_run_min * 60 <= run["elapsed_time"]]
        total = sum(e.carbohydrates_g for e in in_run)
        return {
            "questionnaire_recorded": recorded,
            "pre_run": [e.model_dump(exclude={"food_type"}) for e in questionnaire.pre_run],
            "during_run": [e.model_dump(exclude={"food_type"}) for e in entries],
            "recorded_pre_run_carbs_g": sum(e.carbohydrates_g for e in questionnaire.pre_run),
            "recorded_during_carbs_g": total,
            "recorded_during_carbs_g_per_hour": total * 3600 / run["elapsed_time"]
            if total is not None and run["elapsed_time"] > 0
            else None,
            "excluded_after_finish_entries": len(entries) - len(in_run),
            "limitation": (
                "Rate uses elapsed duration and excludes entries after finish. Absent entries count as zero intake."
            ),
        }

    def _glucose(self, *, args: GlucoseRequest, run: dict[str, Any], run_only: bool = False) -> dict[str, Any]:
        if args.start_min > args.end_min:
            raise ValueError("Start must precede end")
        start = run["start_date_local"]
        lower = start + timedelta(minutes=args.start_min)
        upper = min(start + timedelta(minutes=args.end_min), run["end_date_local"] + timedelta(minutes=5))
        if run_only:
            upper = run["end_date_local"]
        if lower > upper:
            raise ValueError("Requested window is outside the recorded run window")
        frame = (
            self.processor.get_specific_carelink(
                activity_id=args.activity_id, start_datetime=start, end_datetime=run["end_date_local"]
            )
            .filter((pl.col("type") == "CGM") & pl.col("datetime").is_between(lower, upper))
            .sort("datetime")
        )
        valid = frame.drop_nulls("value")
        values = valid["value"].to_list()
        times = valid["datetime"].to_list()
        gaps = [(b - a).total_seconds() / 60 for a, b in zip(times, times[1:], strict=False)]
        metrics = {
            "valid_samples": len(values),
            "missing_samples": len(frame) - len(valid),
            "first_mg_dl": values[0] if values else None,
            "last_mg_dl": values[-1] if values else None,
            "change_mg_dl": values[-1] - values[0] if len(values) >= 2 else None,
            "min_mg_dl": min(values) if values else None,
            "min_time": times[values.index(min(values))] if values else None,
            "mean_mg_dl": sum(values) / len(values) if values else None,
            "samples_in_target_pct": (
                100 * sum(TARGET_GLUCOSE_LOWER <= v <= TARGET_GLUCOSE_UPPER for v in values) / len(values)
            )
            if values
            else None,
            "max_gap_minutes": max(gaps) if gaps else None,
            "first_sample_time": times[0] if times else None,
            "last_sample_time": times[-1] if times else None,
            "target_mg_dl": [TARGET_GLUCOSE_LOWER, TARGET_GLUCOSE_UPPER],
        }
        rows = frame.slice(args.offset, 300).to_dicts()
        return {
            "window_start": lower,
            "window_end": upper,
            "metrics": metrics,
            "measurements": rows,
            "next_offset": args.offset + 300 if args.offset + 300 < len(frame) else None,
            "limitation": "Sample percentages are not time-weighted. No interpolation across gaps. "
            "Local timestamps follow source data; timezone offsets are unavailable.",
        }
