import plotly.graph_objects as go
import polars as pl

from dia_run.data_models.constants import TARGET_GLUCOSE_LOWER, TARGET_GLUCOSE_UPPER
from dia_run.data_models.run_types import RunType
from dia_run.data_processing.data_processing import DataProcessor


def create_run_type_pie_chart(data_processor: DataProcessor) -> go.Figure:
    df_summary = data_processor.get_summary()

    run_type_value_counts = df_summary["run_type"].value_counts()
    fig = go.Figure(
        data=[
            go.Pie(
                labels=run_type_value_counts["run_type"].to_list(),
                values=run_type_value_counts["count"].to_list(),
            )
        ]
    )
    fig.update_layout(title="Run Type Distribution")
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
    fig = go.Figure(
        data=[
            go.Bar(
                x=df_distance["run_type"],
                y=df_distance["distance"],
            )
        ]
    )
    fig.update_layout(
        xaxis={"categoryorder": "array", "categoryarray": run_type_order},
        title="Run Type vs. Total Distance",
        xaxis_title="Run Type",
        yaxis_title="Total Distance [km]",
    )
    return fig


def create_run_type_heartrate_chart(*, data_processor: DataProcessor, run_type_order: list[RunType]) -> go.Figure:
    df_heartrate = data_processor.get_heartrate_streams()
    fig = go.Figure()
    for run_type in run_type_order:
        fig.add_trace(
            go.Box(
                y=df_heartrate.filter(pl.col("run_type") == run_type)["heartrate"],
                name=run_type,
            )
        )
    fig.update_layout(
        title="Run Type vs. Heartrate",
        xaxis_title="Run Type",
        yaxis_title="Heartrate [bpm]",
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
            )
        )
        # highlight the target range
    fig.add_hrect(
        y0=TARGET_GLUCOSE_LOWER,
        y1=TARGET_GLUCOSE_UPPER,
        line_width=0,
        fillcolor="LightGray",
        opacity=0.2,
        layer="below",
    )

    fig.update_layout(
        title="Run Type vs. Sensor Glucose",
        xaxis_title="Run Type",
        yaxis_title="Sensor Glucose [mg/dl]",
    )
    return fig
