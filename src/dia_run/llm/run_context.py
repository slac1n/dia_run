"""Build a plain-text context describing a single run for LLM consumption."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import polars as pl

from dia_run.data_processing.data_processing import DataProcessor

HR_BUCKET_SECONDS = 30


def _fmt(value: Any, *, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _carelink_block(df: pl.DataFrame, *, start_dt: datetime) -> str:
    if df.is_empty():
        return "(no carelink events in window)"
    df_rendered = (
        df.sort("datetime")
        .with_columns(((pl.col("datetime") - start_dt).dt.total_seconds() / 60.0).round(1).alias("min_from_start"))
        .select(["datetime", "min_from_start", "type", "value"])
    )
    lines = ["datetime | min_from_start | type | value"]
    for row in df_rendered.iter_rows(named=True):
        value_str = "" if row["value"] is None else f"{row['value']:.2f}"
        lines.append(f"{row['datetime']} | {row['min_from_start']} | {row['type']} | {value_str}")
    return "\n".join(lines)


def _heartrate_block(df: pl.DataFrame, *, start_dt: datetime) -> str:
    df_hr = df.drop_nulls("heartrate")
    if df_hr.is_empty():
        return "(no heartrate stream)"
    df_bucketed = (
        df_hr.sort("datetime")
        .with_columns(((pl.col("datetime") - start_dt).dt.total_seconds() // HR_BUCKET_SECONDS).alias("_bucket"))
        .group_by("_bucket", maintain_order=True)
        .agg(
            pl.col("datetime").first().alias("datetime"),
            pl.col("heartrate").mean().round(0).cast(pl.Int64).alias("heartrate_avg"),
        )
        .with_columns(
            ((pl.col("datetime") - start_dt).dt.total_seconds() / 60.0).round(2).alias("min_from_start"),
        )
        .select(["min_from_start", "heartrate_avg"])
    )
    lines = [
        f"Downsampled to {HR_BUCKET_SECONDS}s buckets ({len(df_bucketed)} rows).",
        "min_from_start | heartrate_avg",
    ]
    for row in df_bucketed.iter_rows(named=True):
        lines.append(f"{row['min_from_start']} | {row['heartrate_avg']}")
    return "\n".join(lines)


def build_run_context(*, processor: DataProcessor, activity_id: int) -> str:
    """Serialize a single run's data into a plain-text block for an LLM prompt.

    The carelink window is constrained to −180 min to +5 min around the run via
    ``DataProcessor.get_specific_carelink`` — this prevents older backfilled data
    (which stored the full 24 h keyed by ``activity_id``) from leaking into the
    prompt.
    """
    summary = processor.get_summary()
    match = summary.filter(pl.col("activity_id") == activity_id)
    if match.is_empty():
        raise ValueError(f"activity_id {activity_id} not found in summary")
    run = match.row(0, named=True)

    start_dt: datetime = run["start_date_local"]
    end_dt: datetime = run["end_date_local"]

    questionnaire = processor.get_questionnaire(activity_id)
    questionnaire_json = questionnaire.model_dump_json(indent=2)
    iob_str = _fmt(run["insulin_on_board_in_going"], digits=2)

    carelink_df = processor.get_specific_carelink(activity_id=activity_id, start_datetime=start_dt, end_datetime=end_dt)

    hr_all = processor.get_heartrate_streams()
    hr_run = hr_all.filter(
        (pl.col("datetime") >= start_dt - timedelta(minutes=1)) & (pl.col("datetime") <= end_dt + timedelta(minutes=1))
    )

    return f"""Run context — {run["name_date"]}

Target glucose range: 100–180 mg/dL. Insulin-on-board window: 180 min pre-run.

Metadata
- activity_id: {run["activity_id"]}
- name: {run["name"]}
- run_type: {run["run_type"]}
- start_date_local: {start_dt}
- end_date_local: {end_dt}
- distance_km: {run["distance_in_km"]}
- moving_time_sec: {run["moving_time"]}
- elapsed_time_sec: {run["elapsed_time"]} ({run["human_readable_time"]})
- average_pace: {run["human_readable_pace"]} min/km
- average_speed_mps: {_fmt(run.get("average_speed"), digits=2)}
- max_speed_mps: {_fmt(run.get("max_speed"), digits=2)}
- total_elevation_gain_m: {_fmt(run.get("total_elevation_gain"), digits=1)}
- average_heartrate: {_fmt(run.get("average_heartrate"), digits=0)} bpm
- max_heartrate: {_fmt(run.get("max_heartrate"), digits=0)} bpm
- average_watts: {_fmt(run.get("average_watts"), digits=0)}
- max_watts: {_fmt(run.get("max_watts"), digits=0)}
- kilojoules: {_fmt(run.get("kilojoules"), digits=0)}

Glucose summary (run window)
- in_going_sg: {_fmt(run["in_going_sg"], digits=0)} mg/dL
- out_going_sg: {_fmt(run["out_going_sg"], digits=0)} mg/dL
- avg_sg: {_fmt(run["avg_sg"], digits=1)} mg/dL
- tir_pct (100–180): {_fmt(run["tir_pct"], digits=1)}%
- insulin_on_board_in_going (decayed basal+bolus, 180 min pre-run): {iob_str} units

Questionnaire (user-entered context)
- pre_run[]: carbs before run, minutes before start (negative), bolus %, food type.
- basal_adjustments[]: pump adjustments, start/end minutes relative to run start, optional rate %.
  Two types may appear:
    - "Temporal SmartGuard" / "Temporary SmartGuard": sets a different glucose target for a limited
      time while the pump continues to automatically adjust insulin based on CGM data (closed-loop
      automation stays active, just with a new target).
    - "Temporary basal rate" / "Temp basal": manually increases or decreases background insulin by a
      fixed percentage for a set duration, with no automatic adjustments — overrides automation
      entirely for that window.
  Key difference: SmartGuard keeps closed-loop control with a new target; temp basal is a manual
  override that disables automation for the window.
- fueling_during_run[]: carbs during run, minutes from start, food type.
- bolus[]: insulin boluses, minutes from start, units.

{questionnaire_json}

Carelink events
Time window covered: from 180 minutes before run start through 5 minutes after run end.
Every event inside that window is listed below (no data is omitted).
CGM value is mg/dL. AUTO_BASAL_DELIVERY / INSULIN value is units.

{_carelink_block(carelink_df, start_dt=start_dt)}

Heartrate stream during the run
{_heartrate_block(hr_run, start_dt=start_dt)}
"""
