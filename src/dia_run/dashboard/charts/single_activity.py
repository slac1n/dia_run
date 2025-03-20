from datetime import datetime, timedelta

import plotly.graph_objects as go
import polars as pl
from plotly.subplots import make_subplots

from dia_run.data_processing.data_processing import DataProcessor


def create_single_activity_carelink_chart(*, data_processor: DataProcessor, activity_id: int) -> go.Figure:
    df_summary = data_processor.get_summary()
    start_datetime = df_summary.filter(pl.col("activity_id") == activity_id).select("start_date_local")[
        "start_date_local"
    ][0]
    end_datetime = df_summary.filter(pl.col("activity_id") == activity_id).select("end_date_local")["end_date_local"][0]
    sel_df_carelink = data_processor.get_specific_carelink(
        activity_id=activity_id, start_datetime=start_datetime, end_datetime=end_datetime
    )
    sel_df_carelink_cgm = sel_df_carelink.filter(pl.col("type") == "CGM")
    sel_df_carelink_basal = sel_df_carelink.filter(pl.col("type") == "AUTO_BASAL_DELIVERY")
    sel_df_carelink_bolus = sel_df_carelink.filter(pl.col("type") == "INSULIN")

    questionnaire = data_processor.get_questionnaire(activity_id)

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Scatter(
            x=sel_df_carelink_cgm["datetime"],
            y=sel_df_carelink_cgm["value"],
            name="Sensor Glucose",
            mode="lines",
        ),
        secondary_y=False,
    )
    fig.update_yaxes(range=[70, 250], secondary_y=False, title_text="Sensor Glucose [mg/dl]")

    if not sel_df_carelink_basal.is_empty():
        fig.add_trace(
            go.Bar(
                x=sel_df_carelink_basal["datetime"],
                y=sel_df_carelink_basal["value"],
                name="Basal Insulin",
            ),
            secondary_y=True,
        )
        fig.update_yaxes(
            range=[0, 2],
            secondary_y=True,
            showgrid=False,
            showticklabels=False,
        )
    if not sel_df_carelink_bolus.is_empty():
        fig.add_trace(
            go.Bar(
                x=sel_df_carelink_bolus["datetime"],
                y=sel_df_carelink_bolus["value"],
                name="Bolus Insulin",
            ),
            secondary_y=True,
        )

    _add_vertical_line(fig=fig, datetime_instance=start_datetime, color="green", name="Start")
    _add_vertical_line(fig=fig, datetime_instance=end_datetime, color="red", name="End")

    fig.add_shape(
        type="rect",
        xref="x",
        yref="y",
        x0=start_datetime,
        y0=180,
        x1=end_datetime,
        y1=220,
        fillcolor="LightGray",
        opacity=0.2,
        layer="below",
        line_width=0,
    )

    if questionnaire["pre_run"]:
        prerun_time_diff = int(questionnaire["pre_run"]["time_before_start_min"])

        if prerun_time_diff < 0:
            # make time absolute
            prerun_time_diff = abs(prerun_time_diff)
            prerun_time = start_datetime - timedelta(minutes=prerun_time_diff)
            _add_vertical_line(fig=fig, datetime_instance=prerun_time, color="orange", name="Pre-Run Nutrition")

    if questionnaire["fueling_during_run"]:
        for fuel_instance, fuel in enumerate(questionnaire["fueling_during_run"]):
            fuel_time_diff = int(fuel["time_during_run_min"])
            fuel_time = start_datetime + timedelta(minutes=fuel_time_diff)
            _add_vertical_line(
                fig=fig, datetime_instance=fuel_time, color="blue", name=f"Fueling {int(fuel_instance) + 1}"
            )

    return fig


def _add_vertical_line(*, fig: go.Figure, datetime_instance: datetime, color: str, name: str) -> None:
    fig.add_trace(
        go.Scatter(
            x=[datetime_instance, datetime_instance],
            y=[70, 250],
            mode="lines",
            name=name,
            line=dict(color=color, width=1, dash="dash"),
        )
    )
