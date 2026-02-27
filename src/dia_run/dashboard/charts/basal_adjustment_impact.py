import numpy as np
import plotly.graph_objects as go
import polars as pl

from dia_run.dashboard.charts.theme import (
    CHART_GRID,
    MAIN_COLOR,
    get_default_layout,
    get_empty_chart_layout,
)
from dia_run.data_processing.data_processing import DataProcessor


def _get_basal_pct_bucket(*, pct: float | None, adjustment_type: str) -> str:
    """Convert basal setting to display bucket label."""
    if adjustment_type == "Stop Pump":
        return "Pump Suspended"

    if adjustment_type == "Temporal SmartGuard":
        return "SmartGuard"

    if pct is None:
        return "N/A"

    rounded_pct = int(round(pct / 5) * 5)
    return f"{rounded_pct}%"


def create_basal_adjustment_tir_chart(*, data_processor: DataProcessor) -> go.Figure:
    df_tir = data_processor.get_basal_adjustment_tir()

    if df_tir.is_empty():
        fig = go.Figure()
        fig.update_layout(
            **get_empty_chart_layout(
                title="Basal Adjustment vs Time in Range",
                message="No basal adjustment data available",
            )
        )
        return fig

    # Filter out rows with no CGM coverage (require at least 1 minute)
    df_valid = df_tir.filter(pl.col("covered_minutes") >= 1.0).drop_nulls("tir_pct")

    if df_valid.is_empty():
        fig = go.Figure()
        fig.update_layout(
            **get_empty_chart_layout(
                title="Basal Adjustment vs Time in Range",
                message="Insufficient CGM coverage for basal adjustments",
            )
        )
        return fig

    # Add bucket column for all adjustment types (including SmartGuard)
    df_valid = df_valid.with_columns(
        pl.struct(["basal_rate_percentage", "type"])
        .map_elements(
            lambda row: _get_basal_pct_bucket(pct=row["basal_rate_percentage"], adjustment_type=row["type"]),
            return_dtype=pl.Utf8,
        )
        .alias("pct_bucket")
    )

    buckets = df_valid["pct_bucket"].unique().to_list()

    def sort_key(bucket: str) -> tuple[int, int]:
        if bucket == "Pump Suspended":
            return (0, -2)
        if bucket == "SmartGuard":
            return (0, -1)
        if bucket == "N/A":
            return (2, 9999)
        return (1, int(bucket.replace("%", "")))

    sorted_buckets = sorted(buckets, key=sort_key)

    fig = go.Figure()

    for bucket in sorted_buckets:
        df_bucket = df_valid.filter(pl.col("pct_bucket") == bucket)

        fig.add_trace(
            go.Box(
                x=[bucket] * len(df_bucket),
                y=df_bucket["tir_pct"],
                name=bucket,
                legendgroup=bucket,
                showlegend=False,
                marker=dict(
                    size=12,
                    color=MAIN_COLOR,
                    opacity=0.8,
                    line=dict(width=1.5, color=MAIN_COLOR),
                ),
                line=dict(color=MAIN_COLOR, width=2.0),
                width=0.7,
                hovertemplate=(
                    "<b>%{customdata[4]}</b><br>"
                    "Bucket: %{x}<br>"
                    "Basal % Value: %{customdata[3]}<br>"
                    "Activity: %{customdata[0]}<br>"
                    "TIR: %{y:.1f}%<br>"
                    "Duration: %{customdata[1]} min<br>"
                    "CGM coverage: %{customdata[2]:.1f} min"
                    "<extra></extra>"
                ),
                customdata=np.column_stack(
                    [
                        df_bucket["name_date"].to_numpy(),
                        df_bucket["duration_min"].to_numpy(),
                        df_bucket["covered_minutes"].to_numpy(),
                        df_bucket["basal_rate_percentage"].cast(pl.Utf8).fill_null("N/A").to_numpy(),
                        df_bucket["type"].to_numpy(),
                    ]
                ),
            )
        )

    layout = get_default_layout(
        title="Basal Adjustment vs Time in Range",
        xaxis_title="Basal Rate Bucket",
        yaxis_title="Time in Range [%]",
        height=450,
    )
    layout["margin"] = {"l": 60, "r": 30, "t": 50, "b": 80}
    fig.update_layout(**layout)

    fig.update_xaxes(
        categoryorder="array",
        categoryarray=sorted_buckets,
        tickangle=-45,
        showgrid=False,
    )
    fig.update_yaxes(
        range=[0, 105],
        gridcolor=CHART_GRID,
        zerolinecolor=CHART_GRID,
        showgrid=True,
    )

    return fig
