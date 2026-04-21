import numpy as np
import plotly.graph_objects as go
import polars as pl
from plotly.subplots import make_subplots

from dia_run.dashboard.charts.theme import (
    CHART_GRID,
    MAIN_COLOR,
    MAIN_COLOR_SHADE_500,
    get_bottom_legend,
    get_default_layout,
    get_empty_chart_layout,
    get_exploratory_marker,
)
from dia_run.data_processing.data_processing import DataProcessor

ACTIONABLE_THRESHOLD = 8
_BASAL_LEAD_TIME_ORDER = ["none", "0-30", "31-60", "61-90", ">90"]


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


def _sort_by_order(df: pl.DataFrame, *, order: list[str]) -> pl.DataFrame:
    order_map = {key: idx for idx, key in enumerate(order)}
    return (
        df.with_columns(
            pl.col("bucket_key")
            .replace_strict(order_map, default=len(order_map), return_dtype=pl.Int64)
            .alias("_order_key")
        )
        .sort("_order_key")
        .drop("_order_key")
    )


def _tick_labels_with_exploratory(*, keys: list[str], n_values: list[int]) -> list[str]:
    return [
        f"{k} (n<{ACTIONABLE_THRESHOLD})" if n < ACTIONABLE_THRESHOLD else k
        for k, n in zip(keys, n_values, strict=True)
    ]


def create_basal_lead_time_effect_chart(*, data_processor: DataProcessor) -> go.Figure:
    df = data_processor.get_basal_lead_time_effect()
    if df.is_empty():
        fig = go.Figure()
        fig.update_layout(
            **get_empty_chart_layout(
                title="Basal lead-time vs TIR and early stability",
                message="No runs available",
            )
        )
        return fig

    df = _sort_by_order(df, order=_BASAL_LEAD_TIME_ORDER)
    keys = df["bucket_key"].to_list()
    n_values = df["n"].to_list()
    tir_median = df["tir_median"].to_list()
    stable_rate = [round(v * 100, 1) if v is not None else None for v in df["stable_20_rate"].to_list()]
    x_labels = _tick_labels_with_exploratory(keys=keys, n_values=n_values)

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            name="TIR median",
            x=x_labels,
            y=tir_median,
            marker=get_exploratory_marker(n_values=n_values, base_color=MAIN_COLOR, threshold=ACTIONABLE_THRESHOLD),
            text=[f"n={n}" for n in n_values],
            textposition="outside",
            hovertemplate="<b>TIR</b><br>Lead-time: %{x}<br>Median: %{y:.1f}%<br>n=%{customdata}<extra></extra>",
            customdata=n_values,
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            name="Stable first 20 min rate",
            x=x_labels,
            y=stable_rate,
            mode="lines+markers",
            line={"color": MAIN_COLOR_SHADE_500, "width": 2.5},
            marker={"size": 9, "color": MAIN_COLOR_SHADE_500},
            hovertemplate="<b>Stable rate</b><br>Lead-time: %{x}<br>Rate: %{y:.1f}%<extra></extra>",
        ),
        secondary_y=True,
    )

    layout = get_default_layout(
        title="Basal lead-time vs TIR and early stability",
        xaxis_title="Lead-time before run (min)",
        height=420,
        showlegend=True,
    )
    layout["legend"] = get_bottom_legend()
    fig.update_layout(**layout)
    fig.update_yaxes(title_text="TIR median [%]", range=[0, 110], secondary_y=False)
    fig.update_yaxes(title_text="Stable first 20 rate [%]", range=[0, 110], secondary_y=True, showgrid=False)
    return fig
