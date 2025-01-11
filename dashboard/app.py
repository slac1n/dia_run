from pathlib import Path

import polars as pl
import streamlit as st

STRAVA_SUMMARY_DIR = Path("data") / "strava" / "summary"
CARELINK_DIR = Path("data") / "carelink"

# Load the Delta table using pl.scan_delta
df_summary = pl.scan_delta(str(STRAVA_SUMMARY_DIR)).with_columns(
    pl.format(
        "{}:{}",
        (pl.col("elapsed_time") // 3600),  # Hours
        (pl.col("elapsed_time") % 3600) // 60,  # Minutes
    ).alias("human_readable_time"),
    pl.format(
        "{}:{}",
        (pl.col("average_pace").floor().cast(int)),  # Minutes
        ((pl.col("average_pace") % 1) * 60)
        .round(0)
        .cast(int),  # Fractional minutes to seconds
    ).alias("human_readable_pace"),
    pl.format(
        "{}",
        (pl.col("distance") / 1000).round(1),  # Convert meters to kilometers
    ).alias("distance_in_km"),
    (pl.col("start_date_local") + pl.duration(seconds=pl.col("elapsed_time"))).alias(
        "end_date_local"
    ),
)

df_carelink = (
    pl.scan_delta(str(CARELINK_DIR))
    .filter(pl.col("type") == "CGM")
    .join(
        df_summary.select("activity_id", "start_date_local", "end_date_local"),
        on="activity_id",
        how="inner",
    )
    .filter(
        (pl.col("datetime") >= pl.col("start_date_local") - pl.duration(minutes=5))
        & (pl.col("datetime") <= pl.col("end_date_local") + pl.duration(minutes=5))
    )
    .group_by("activity_id")
    .agg(
        [
            pl.col("value").first().alias("in_going_sg"),
            pl.col("value").last().alias("out_going_sg"),
            pl.col("value").mean().alias("avg_sg"),
        ]
    )
)

df_summary = df_summary.join(
    df_carelink,
    on="activity_id",
    how="left",
)

# Collect the dataframes
df_carelink = df_carelink.collect()
df_summary = df_summary.collect()
st.write("Overview table of running activities")
st.write(
    df_summary.select(
        "name",
        "distance_in_km",
        "human_readable_time",
        "human_readable_pace",
        "average_heartrate",
        "kilojoules",
        "in_going_sg",
        "out_going_sg",
        "avg_sg",
    )
)
