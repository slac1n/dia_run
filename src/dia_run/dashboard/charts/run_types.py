import plotly.graph_objects as go
import polars as pl

from dia_run.dashboard.charts.theme import MAIN_COLOR, NAVY, TARGET_RANGE_FILL, get_color_for_index, get_default_layout
from dia_run.data_models.constants import TARGET_GLUCOSE_LOWER, TARGET_GLUCOSE_UPPER
from dia_run.data_models.run_types import RunType
from dia_run.data_processing.data_processing import DataProcessor


def _build_run_type_color_map(*, run_type_order: list[RunType]) -> dict[RunType, str]:
    return {run_type: get_color_for_index(idx) for idx, run_type in enumerate(run_type_order)}


def create_run_type_pie_chart(*, data_processor: DataProcessor, run_type_order: list[RunType]) -> go.Figure:
    df_summary = data_processor.get_summary()

    run_type_value_counts = df_summary["run_type"].value_counts()
    labels = run_type_value_counts["run_type"].to_list()
    color_map = _build_run_type_color_map(run_type_order=run_type_order)
    fig = go.Figure(
        data=[
            go.Pie(
                labels=labels,
                values=run_type_value_counts["count"].to_list(),
                marker={"colors": [color_map.get(label, get_color_for_index(idx)) for idx, label in enumerate(labels)]},
            )
        ]
    )
    fig.update_layout(
        **get_default_layout(
            title="Run Type Distribution",
            showlegend=True,
        )
    )
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
                line={"color": NAVY},
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
                line={"color": NAVY},
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
