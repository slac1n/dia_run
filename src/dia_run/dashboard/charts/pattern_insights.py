import plotly.graph_objects as go
import polars as pl
from plotly.subplots import make_subplots

from dia_run.dashboard.charts.theme import (
    MAIN_COLOR,
    MAIN_COLOR_SHADE_300,
    MAIN_COLOR_SHADE_500,
    get_bottom_legend,
    get_default_layout,
    get_empty_chart_layout,
    get_exploratory_marker,
)
from dia_run.data_processing.data_processing import DataProcessor

ACTIONABLE_THRESHOLD = 8

_GLUCOSE_BAND_ORDER = ["<100", "100-129", "130-159", "160-180", ">180"]
_TIME_OF_DAY_ORDER = ["morning", "evening"]
_TIME_OF_DAY_LABELS = {"morning": "Morning", "evening": "Evening"}


def _tick_labels_with_exploratory(*, keys: list[str], n_values: list[int]) -> list[str]:
    return [
        f"{k} (n<{ACTIONABLE_THRESHOLD})" if n < ACTIONABLE_THRESHOLD else k
        for k, n in zip(keys, n_values, strict=True)
    ]


def _sort_by_order(df: pl.DataFrame, *, order: list[str], column: str = "bucket_key") -> pl.DataFrame:
    order_map = {key: idx for idx, key in enumerate(order)}
    return (
        df.with_columns(
            pl.col(column).replace_strict(order_map, default=len(order_map), return_dtype=pl.Int64).alias("_order_key")
        )
        .sort("_order_key")
        .drop("_order_key")
    )


def create_time_of_day_outcomes_chart(*, data_processor: DataProcessor) -> go.Figure:
    df = data_processor.get_time_of_day_outcomes()
    if df.is_empty():
        fig = go.Figure()
        fig.update_layout(**get_empty_chart_layout(title="Outcomes by time of day", message="No runs available"))
        return fig

    df = _sort_by_order(df, order=_TIME_OF_DAY_ORDER)
    labels = [_TIME_OF_DAY_LABELS.get(k, k) for k in df["bucket_key"].to_list()]
    n_values = df["n"].to_list()

    metrics = [
        ("TIR", df["tir_median"].to_list(), MAIN_COLOR),
        ("Good finish", [_pct(v) for v in df["good_finish_rate"].to_list()], MAIN_COLOR_SHADE_500),
        ("Low event", [_pct(v) for v in df["low_event_rate"].to_list()], MAIN_COLOR_SHADE_300),
    ]

    fig = go.Figure()
    for name, values, color in metrics:
        fig.add_trace(
            go.Bar(
                name=name,
                x=labels,
                y=values,
                marker=get_exploratory_marker(n_values=n_values, base_color=color, threshold=ACTIONABLE_THRESHOLD),
                text=[f"n={n}" for n in n_values],
                textposition="outside",
                hovertemplate=f"<b>{name}</b><br>%{{x}}<br>Value: %{{y:.1f}}%<br>n=%{{customdata}}<extra></extra>",
                customdata=n_values,
            )
        )

    layout = get_default_layout(
        title="Outcomes by time of day",
        xaxis_title="Time of day",
        yaxis_title="Rate / TIR [%]",
        height=380,
        showlegend=True,
    )
    layout["barmode"] = "group"
    layout["legend"] = get_bottom_legend()
    fig.update_layout(**layout)
    fig.update_yaxes(range=[0, 110])
    return fig


def create_first20_stability_effect_chart(*, data_processor: DataProcessor) -> go.Figure:
    df = data_processor.get_first20_stability_effect()
    if df.is_empty():
        fig = go.Figure()
        fig.update_layout(
            **get_empty_chart_layout(title="First 20 minutes: stable vs unstable", message="No runs with CGM coverage")
        )
        return fig

    df = df.sort("bucket_key", descending=True)
    label_map = {"true": "Stable first 20 min", "false": "Unstable first 20 min"}
    n_values = df["n"].to_list()
    labels = [f"{label_map.get(k, k)} (n={n})" for k, n in zip(df["bucket_key"].to_list(), n_values, strict=True)]

    metrics = [
        ("TIR median [%]", df["tir_median"].to_list(), MAIN_COLOR),
        ("Good finish [%]", [_pct(v) for v in df["good_finish_rate"].to_list()], MAIN_COLOR_SHADE_500),
        ("Low event [%]", [_pct(v) for v in df["low_event_rate"].to_list()], MAIN_COLOR_SHADE_300),
        (
            "Variability P90-P10 [mg/dL]",
            df["variability_median"].to_list(),
            "#8fb5ab",
        ),
    ]

    fig = go.Figure()
    for name, values, color in metrics:
        fig.add_trace(
            go.Bar(
                name=name,
                x=labels,
                y=values,
                marker=get_exploratory_marker(n_values=n_values, base_color=color, threshold=ACTIONABLE_THRESHOLD),
                text=[f"n={n}" for n in n_values],
                textposition="outside",
                hovertemplate=f"<b>{name}</b><br>%{{x}}<br>Value: %{{y:.1f}}<br>n=%{{customdata}}<extra></extra>",
                customdata=n_values,
            )
        )

    layout = get_default_layout(
        title="First 20 minutes: stability impact",
        xaxis_title="Group",
        yaxis_title="Value",
        height=420,
        showlegend=True,
    )
    layout["barmode"] = "group"
    layout["legend"] = get_bottom_legend()
    fig.update_layout(**layout)
    return fig


def create_sg20_predictor_chart(*, data_processor: DataProcessor) -> go.Figure:
    df = data_processor.get_sg20_predictor()
    if df.is_empty():
        fig = go.Figure()
        fig.update_layout(
            **get_empty_chart_layout(
                title="Glucose at +20 min as predictor",
                message="No runs with CGM near the 20-minute mark",
            )
        )
        return fig

    df = _sort_by_order(df, order=_GLUCOSE_BAND_ORDER)
    keys = df["bucket_key"].to_list()
    n_values = df["n"].to_list()
    good_finish = [_pct(v) for v in df["good_finish_rate"].to_list()]
    tir_median = df["tir_median"].to_list()
    x_labels = _tick_labels_with_exploratory(keys=keys, n_values=n_values)

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            name="Good finish rate",
            x=x_labels,
            y=good_finish,
            marker=get_exploratory_marker(
                n_values=n_values, base_color=MAIN_COLOR_SHADE_500, threshold=ACTIONABLE_THRESHOLD
            ),
            text=[f"n={n}" for n in n_values],
            textposition="outside",
            hovertemplate="<b>Good finish</b><br>SG@20: %{x}<br>Rate: %{y:.1f}%<br>n=%{customdata}<extra></extra>",
            customdata=n_values,
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            name="TIR median",
            x=x_labels,
            y=tir_median,
            mode="lines+markers",
            line={"color": MAIN_COLOR, "width": 2.5},
            marker={"size": 9, "color": MAIN_COLOR},
            hovertemplate="<b>TIR median</b><br>SG@20: %{x}<br>Median: %{y:.1f}%<extra></extra>",
        ),
        secondary_y=True,
    )

    layout = get_default_layout(
        title="Glucose at +20 min as predictor",
        xaxis_title="Glucose at +20 min [mg/dL]",
        height=420,
        showlegend=True,
    )
    layout["legend"] = get_bottom_legend()
    fig.update_layout(**layout)
    fig.update_yaxes(title_text="Good finish rate [%]", range=[0, 110], secondary_y=False)
    fig.update_yaxes(title_text="TIR median [%]", range=[0, 110], secondary_y=True, showgrid=False)
    return fig


def create_similar_runs_benchmark_chart(*, data_processor: DataProcessor) -> go.Figure:
    df = data_processor.get_similar_runs_cohorts().filter(pl.col("actionable"))

    if df.is_empty():
        fig = go.Figure()
        fig.update_layout(
            **get_empty_chart_layout(
                title="Similar-runs benchmark",
                message=f"Collect more data - no cohort has n >= {ACTIONABLE_THRESHOLD}",
            )
        )
        return fig

    df = df.sort("tir_median", descending=False)
    labels = df["bucket_key"].to_list()
    n_values = df["n"].to_list()
    tir_median = df["tir_median"].to_list()
    good_finish = [_pct(v) for v in df["good_finish_rate"].to_list()]
    low_event = [_pct(v) for v in df["low_event_rate"].to_list()]

    fig = go.Figure(
        data=[
            go.Bar(
                orientation="h",
                x=tir_median,
                y=labels,
                marker={"color": MAIN_COLOR, "line": {"width": 1, "color": MAIN_COLOR_SHADE_500}},
                text=[f"TIR {tir:.0f}% · n={n}" for tir, n in zip(tir_median, n_values, strict=True)],
                textposition="outside",
                customdata=list(zip(n_values, good_finish, low_event, strict=True)),
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "TIR median: %{x:.1f}%<br>"
                    "Good finish: %{customdata[1]:.1f}%<br>"
                    "Low event: %{customdata[2]:.1f}%<br>"
                    "n=%{customdata[0]}"
                    "<extra></extra>"
                ),
            )
        ]
    )
    layout = get_default_layout(
        title="Similar-runs benchmark",
        xaxis_title="TIR median [%]",
        yaxis_title="Cohort (run type | duration | start glucose)",
        height=max(300, 40 * len(labels) + 120),
    )
    fig.update_layout(**layout)
    fig.update_xaxes(range=[0, 110])
    return fig


def _pct(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 100, 1)
