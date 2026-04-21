import numpy as np
import plotly.graph_objects as go
import polars as pl

from dia_run.dashboard.charts.theme import (
    COLOR_MUTED,
    MAIN_COLOR,
    MAIN_COLOR_SHADE_300,
    MAIN_COLOR_SHADE_500,
    NAVY,
    SANDY,
    TOMATO,
    get_bottom_legend,
    get_default_layout,
    get_empty_chart_layout,
    get_exploratory_marker,
)
from dia_run.data_processing.data_processing import DataProcessor

ACTIONABLE_THRESHOLD = 8
_FUELING_TIMING_ORDER = ["0-15", "16-30", "31-60", "61-90", ">90"]
_GLUCOSE_BAND_ORDER = ["<100", "100-129", "130-159", "160-180", ">180"]


def _add_event_annotation(*, fig: go.Figure, x_value: int, text: str, color: str) -> None:
    fig.add_annotation(
        x=x_value,
        y=1.05,
        xref="x",
        yref="paper",
        text=text,
        showarrow=False,
        bgcolor="rgba(255, 255, 255, 0.92)",
        bordercolor="rgba(47, 62, 70, 0.14)",
        borderwidth=1,
        font={"color": color, "size": 10},
        xanchor="center",
        yanchor="bottom",
    )


def _interpolate_to_minute_bins(df: pl.DataFrame, *, minute_bins: list[int]) -> pl.DataFrame:
    interpolated_rows = []
    for (activity_id, fueling_index), group in df.group_by(["activity_id", "fueling_index"]):
        group_sorted = group.sort("minutes_relative")
        minutes_arr = group_sorted["minutes_relative"].to_numpy()
        values_arr = group_sorted["value"].to_numpy()

        valid_mask = ~np.isnan(values_arr)
        if valid_mask.sum() < 2:
            continue

        valid_minutes = minutes_arr[valid_mask]
        valid_values = values_arr[valid_mask]
        min_valid = valid_minutes.min()
        max_valid = valid_minutes.max()

        for minute in minute_bins:
            if minute < min_valid or minute > max_valid:
                continue

            value = np.interp(minute, valid_minutes, valid_values)
            interpolated_rows.append(
                {
                    "activity_id": activity_id,
                    "fueling_index": fueling_index,
                    "minutes_relative": minute,
                    "value": value,
                }
            )

    return (
        pl.DataFrame(interpolated_rows)
        if interpolated_rows
        else pl.DataFrame(
            schema={
                "activity_id": pl.Int64,
                "fueling_index": pl.Int64,
                "minutes_relative": pl.Int64,
                "value": pl.Float64,
            }
        )
    )


def create_fueling_glucose_response_chart(*, data_processor: DataProcessor) -> go.Figure:
    df_windows = data_processor.get_fueling_glucose_windows()

    if df_windows.is_empty():
        fig = go.Figure()
        fig.update_layout(
            **get_empty_chart_layout(
                title="Glucose Response After Fueling",
                message="No fueling data available",
            )
        )
        return fig

    fig = go.Figure()

    minute_values = df_windows["minutes_relative"].to_numpy().astype(int)
    min_minute = int(minute_values.min())
    max_minute = int(minute_values.max())
    minute_bins = list(range(min_minute, max_minute + 1))

    df_interpolated = _interpolate_to_minute_bins(df_windows, minute_bins=minute_bins)

    baseline_df = (
        df_interpolated.with_columns(pl.col("minutes_relative").abs().alias("abs_minutes"))
        .sort("abs_minutes")
        .group_by(["activity_id", "fueling_index"])
        .first()
        .select(["activity_id", "fueling_index", "value"])
        .rename({"value": "baseline_value"})
    )

    df_normalized = df_interpolated.join(baseline_df, on=["activity_id", "fueling_index"]).with_columns(
        (pl.col("value") - pl.col("baseline_value")).alias("value_change")
    )

    event_groups = df_normalized.group_by(["activity_id", "fueling_index"]).agg(
        pl.col("minutes_relative"),
        pl.col("value_change"),
    )

    for row in event_groups.iter_rows(named=True):
        minutes = row["minutes_relative"]
        values = row["value_change"]

        fig.add_trace(
            go.Scatter(
                x=minutes,
                y=values,
                mode="lines",
                showlegend=False,
                line=dict(width=1, dash="dash", color="rgba(47, 62, 70, 0.16)"),
                hovertemplate="Min: %{x:.0f}<br>Change: %{y:+.0f} mg/dL<extra></extra>",
            )
        )

    df_mean = (
        df_normalized.group_by("minutes_relative")
        .agg(
            pl.col("value_change").mean().alias("mean_value"),
            pl.col("value_change").quantile(0.25).alias("q1_value"),
            pl.col("value_change").quantile(0.75).alias("q3_value"),
            pl.struct(["activity_id", "fueling_index"]).n_unique().alias("n_contributing"),
        )
        .filter(pl.col("n_contributing") >= 3)
        .sort("minutes_relative")
    )

    if not df_mean.is_empty():
        fig.add_trace(
            go.Scatter(
                x=df_mean["minutes_relative"],
                y=df_mean["q3_value"],
                mode="lines",
                showlegend=False,
                line=dict(width=0),
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df_mean["minutes_relative"],
                y=df_mean["q1_value"],
                mode="lines",
                showlegend=False,
                line=dict(width=0),
                fill="tonexty",
                fillcolor="rgba(82, 121, 111, 0.18)",
                hovertemplate="IQR: %{y:+.0f} mg/dL<extra></extra>",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df_mean["minutes_relative"],
                y=df_mean["mean_value"],
                mode="lines",
                name="Mean Response",
                showlegend=False,
                line=dict(color=NAVY, width=3.5),
                hovertemplate="Min: %{x:.0f}<br>Mean Change: %{y:+.0f} mg/dL<extra></extra>",
            )
        )

        minutes = df_mean["minutes_relative"].to_numpy()
        values = df_mean["mean_value"].to_numpy()

        post_intake_mask = minutes > 0
        post_intake_minutes = minutes[post_intake_mask]
        post_intake_values = values[post_intake_mask]

        if len(post_intake_minutes) > 0:
            min_idx = np.argmin(post_intake_values)
            lowest_point_minute = int(post_intake_minutes[min_idx])
            lowest_point_value = post_intake_values[min_idx]

            if lowest_point_value < 0:
                fig.add_vline(
                    x=lowest_point_minute,
                    line_dash="dot",
                    line_color=TOMATO,
                    line_width=2,
                )
                _add_event_annotation(
                    fig=fig, x_value=lowest_point_minute, text=f"Low +{lowest_point_minute}", color=TOMATO
                )

            after_lowest_mask = post_intake_minutes >= lowest_point_minute
            after_lowest_minutes = post_intake_minutes[after_lowest_mask]
            after_lowest_values = post_intake_values[after_lowest_mask]

            crosses_zero = np.where(np.diff(np.sign(after_lowest_values)))[0]
            if len(crosses_zero) > 0:
                first_cross_idx = crosses_zero[0]
                return_to_baseline_minute = int(after_lowest_minutes[first_cross_idx])
                fig.add_vline(
                    x=return_to_baseline_minute,
                    line_dash="dot",
                    line_color=MAIN_COLOR_SHADE_500,
                    line_width=2,
                )
                _add_event_annotation(
                    fig=fig,
                    x_value=return_to_baseline_minute,
                    text=f"Base +{return_to_baseline_minute}",
                    color=MAIN_COLOR_SHADE_500,
                )

    fig.add_vline(
        x=0,
        line_dash="dash",
        line_color=SANDY,
        line_width=2,
    )
    _add_event_annotation(fig=fig, x_value=0, text="Intake", color=SANDY)

    layout = get_default_layout(
        title="Glucose Response After Fueling",
        xaxis_title="Minutes Relative to Fueling",
        yaxis_title="Glucose Change [mg/dL]",
        height=360,
        showlegend=False,
    )
    layout["margin"] = {"l": 56, "r": 20, "t": 52, "b": 64}
    fig.update_layout(**layout)
    fig.update_xaxes(
        range=[-DataProcessor.PRE_INTAKE_WINDOW_MINUTES, DataProcessor.FUELING_WINDOW_MINUTES],
        autorange=False,
        tickfont={"color": COLOR_MUTED},
    )

    return fig


def create_fueling_carbs_vs_peak_chart(*, data_processor: DataProcessor) -> go.Figure:
    df_impact = data_processor.get_fueling_impact()

    df_valid = df_impact.drop_nulls(subset=["peak_increase", "carbohydrates_g"])

    if df_valid.is_empty():
        fig = go.Figure()
        fig.update_layout(
            **get_empty_chart_layout(
                title="Carbohydrate Intake vs. Peak Glucose Increase",
                message="No fueling impact data available",
            )
        )
        return fig

    carbs = df_valid["carbohydrates_g"].to_numpy()
    peak_increase = df_valid["peak_increase"].to_numpy()

    jitter = np.random.default_rng(17).uniform(-1.0, 1.0, size=len(carbs))
    carbs_jittered = carbs + jitter

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=carbs_jittered,
            y=peak_increase,
            mode="markers",
            marker=dict(
                size=12,
                color=MAIN_COLOR_SHADE_500,
                opacity=0.72,
                line=dict(width=1, color=NAVY),
            ),
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Carbs: %{x}g<br>"
                "Peak Increase: %{y:.0f} mg/dL<br>"
                "Time to Peak: %{customdata[1]:.0f} min<br>"
                "Baseline SG: %{customdata[2]:.0f} mg/dL"
                "<extra></extra>"
            ),
            customdata=np.column_stack(
                [
                    df_valid["name_date"].to_numpy(),
                    df_valid["time_to_peak_min"].to_numpy(),
                    df_valid["baseline_sg"].to_numpy(),
                ]
            ),
            name="Fueling Events",
        )
    )

    layout = get_default_layout(
        title="Carbohydrate Intake vs. Peak Glucose Increase",
        xaxis_title="Carbohydrates [g]",
        yaxis_title="Peak Glucose Increase [mg/dL]",
        height=360,
    )
    layout["margin"] = {"l": 56, "r": 20, "t": 28, "b": 64}
    fig.update_layout(**layout)

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


def _pct(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 100, 1)


def _build_fueling_side_by_side(
    *,
    df: pl.DataFrame,
    title: str,
    xaxis_title: str,
    empty_message: str,
) -> go.Figure:
    if df.is_empty():
        fig = go.Figure()
        fig.update_layout(**get_empty_chart_layout(title=title, message=empty_message))
        return fig

    n_values = df["n"].to_list()
    labels = [f"{k}<br>(n={n})" for k, n in zip(df["bucket_key"].to_list(), n_values, strict=True)]

    metrics = [
        ("Post-TIR", [_pct(v) for v in df["post_tir_rate"].to_list()], MAIN_COLOR),
        ("Avoided low", [_pct(v) for v in df["avoided_low_rate"].to_list()], MAIN_COLOR_SHADE_500),
        ("No spike", [_pct(v) for v in df["peak_no_spike_rate"].to_list()], MAIN_COLOR_SHADE_300),
    ]

    fig = go.Figure()
    for name, values, color in metrics:
        fig.add_trace(
            go.Bar(
                name=name,
                x=labels,
                y=values,
                marker=get_exploratory_marker(n_values=n_values, base_color=color, threshold=ACTIONABLE_THRESHOLD),
                hovertemplate=f"<b>{name}</b><br>%{{x}}<br>Value: %{{y:.1f}}%<br>n=%{{customdata}}<extra></extra>",
                customdata=n_values,
            )
        )

    layout = get_default_layout(
        title=title,
        xaxis_title=xaxis_title,
        yaxis_title="Rate [%]",
        height=420,
        showlegend=True,
    )
    layout["barmode"] = "group"
    layout["legend"] = get_bottom_legend()
    fig.update_layout(**layout)
    fig.update_yaxes(range=[0, 110])
    return fig


def create_fueling_timing_chart(*, data_processor: DataProcessor) -> go.Figure:
    df = data_processor.get_fueling_timing_effect()
    df = _sort_by_order(df, order=_FUELING_TIMING_ORDER)
    return _build_fueling_side_by_side(
        df=df,
        title="Best time to fuel during the run",
        xaxis_title="Minutes into run",
        empty_message="No fueling events available",
    )


def create_fueling_sg_chart(*, data_processor: DataProcessor) -> go.Figure:
    df = data_processor.get_fueling_sg_effect()
    df = _sort_by_order(df, order=_GLUCOSE_BAND_ORDER)
    return _build_fueling_side_by_side(
        df=df,
        title="Best SG level when fueling",
        xaxis_title="SG at fueling [mg/dL]",
        empty_message="No fueling events with baseline SG",
    )
