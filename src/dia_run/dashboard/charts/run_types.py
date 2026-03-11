import plotly.graph_objects as go
import polars as pl

from dia_run.dashboard.charts.theme import (
    MAIN_COLOR,
    TARGET_RANGE_FILL,
    get_bottom_legend,
    get_color_for_index,
    get_default_layout,
)
from dia_run.data_models.constants import TARGET_GLUCOSE_LOWER, TARGET_GLUCOSE_UPPER
from dia_run.data_models.run_types import RunType
from dia_run.data_processing.data_processing import DataProcessor


def _build_run_type_color_map(*, run_type_order: list[RunType]) -> dict[str, str]:
    return {str(run_type): get_color_for_index(idx) for idx, run_type in enumerate(run_type_order)}


def create_run_type_pie_chart(*, data_processor: DataProcessor, run_type_order: list[RunType]) -> go.Figure:
    df_summary = data_processor.get_summary()

    run_type_value_counts = {
        str(row["run_type"]): int(row["count"]) for row in df_summary["run_type"].value_counts().iter_rows(named=True)
    }
    ordered_run_types = [str(run_type) for run_type in run_type_order if str(run_type) in run_type_value_counts]
    remaining_run_types = sorted(label for label in run_type_value_counts if label not in set(ordered_run_types))
    labels = [*ordered_run_types, *remaining_run_types]
    values = [run_type_value_counts[label] for label in labels]
    color_map = _build_run_type_color_map(run_type_order=run_type_order)
    fig = go.Figure(
        data=[
            go.Pie(
                labels=labels,
                values=values,
                sort=False,
                rotation=0,
                direction="clockwise",
                textinfo="percent",
                textposition="inside",
                insidetextorientation="radial",
                marker={"colors": [color_map.get(label, get_color_for_index(idx)) for idx, label in enumerate(labels)]},
            )
        ]
    )
    layout = get_default_layout(title="Run Type Distribution", height=380, showlegend=True)
    layout["legend"] = get_bottom_legend(y=-0.12) | {"x": 0.5, "xanchor": "center"}
    layout["margin"] = {"l": 20, "r": 20, "t": 28, "b": 100}
    fig.update_layout(**layout)
    return fig


def create_run_type_distance_chart(*, data_processor: DataProcessor, run_type_order: list[RunType]) -> go.Figure:
    df_summary = data_processor.get_summary()
    df_distance = (
        df_summary.group_by("run_type")
        .agg(pl.sum("distance"))
        .with_columns(
            pl.col("distance") / 1000,
        )
    )
    color_map = _build_run_type_color_map(run_type_order=run_type_order)
    run_types = df_distance["run_type"].to_list()
    fig = go.Figure(
        data=[
            go.Bar(
                x=df_distance["run_type"],
                y=df_distance["distance"],
                marker={
                    "color": [
                        color_map.get(run_type, get_color_for_index(idx)) for idx, run_type in enumerate(run_types)
                    ]
                },
            )
        ]
    )
    fig.update_layout(
        **get_default_layout(
            title="Run Type vs. Total Distance",
            xaxis_title="Run Type",
            yaxis_title="Total Distance [km]",
        )
    )
    fig.update_xaxes(categoryorder="array", categoryarray=run_type_order)
    return fig


def create_run_type_heartrate_chart(*, data_processor: DataProcessor, run_type_order: list[RunType]) -> go.Figure:
    df_heartrate = data_processor.get_heartrate_streams()
    fig = go.Figure()
    for run_type in run_type_order:
        fig.add_trace(
            go.Box(
                y=df_heartrate.filter(pl.col("run_type") == run_type)["heartrate"],
                name=run_type,
                marker={"color": MAIN_COLOR},
                line={"color": MAIN_COLOR},
            )
        )
    fig.update_layout(
        **get_default_layout(
            title="Run Type vs. Heartrate",
            xaxis_title="Run Type",
            yaxis_title="Heartrate [bpm]",
        )
    )
    return fig


def create_run_type_glucose_chart(*, data_processor: DataProcessor, run_type_order: list[RunType]) -> go.Figure:
    df_glucose = data_processor.get_glucose_streams()
    fig = go.Figure()
    for run_type in run_type_order:
        fig.add_trace(
            go.Box(
                y=df_glucose.filter(pl.col("run_type") == run_type)["value"],
                name=run_type,
                marker={"color": MAIN_COLOR},
                line={"color": MAIN_COLOR},
            )
        )
        # highlight the target range
    fig.add_hrect(
        y0=TARGET_GLUCOSE_LOWER,
        y1=TARGET_GLUCOSE_UPPER,
        line_width=0,
        fillcolor=TARGET_RANGE_FILL,
        opacity=0.3,
        layer="below",
    )

    fig.update_layout(
        **get_default_layout(
            title="Run Type vs. Sensor Glucose",
            xaxis_title="Run Type",
            yaxis_title="Sensor Glucose [mg/dl]",
        )
    )
    return fig
