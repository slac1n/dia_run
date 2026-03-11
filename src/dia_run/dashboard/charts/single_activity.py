from datetime import datetime, timedelta

import plotly.graph_objects as go
import polars as pl
from plotly.subplots import make_subplots

from dia_run.dashboard.charts.theme import (
    COLOR_SUCCESS,
    GOLD,
    NAVY,
    SANDY,
    TARGET_RANGE_FILL,
    TOMATO,
    get_bottom_legend,
    get_default_layout,
)
from dia_run.data_models.constants import TARGET_GLUCOSE_LOWER, TARGET_GLUCOSE_UPPER
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
            line=dict(color=NAVY, width=2.4),
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
                marker=dict(color=GOLD, opacity=0.6),
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
                marker=dict(color=SANDY, opacity=0.72),
            ),
            secondary_y=True,
        )

    _add_vertical_line(
        fig=fig,
        datetime_instance=start_datetime,
        color=COLOR_SUCCESS,
        name="Start",
        dash="solid",
        width=2.4,
    )
    _add_event_band(fig=fig, start_time=start_datetime, color=COLOR_SUCCESS, width_minutes=2.0)
    _add_vertical_line(
        fig=fig,
        datetime_instance=end_datetime,
        color=TOMATO,
        name="End",
        dash="longdash",
        width=2.4,
    )
    _add_event_band(fig=fig, start_time=end_datetime, color=TOMATO, width_minutes=2.0)

    fig.add_shape(
        type="rect",
        xref="x",
        yref="y",
        x0=start_datetime,
        y0=TARGET_GLUCOSE_LOWER,
        x1=end_datetime,
        y1=TARGET_GLUCOSE_UPPER,
        fillcolor=TARGET_RANGE_FILL,
        opacity=0.3,
        layer="below",
        line_width=0,
    )

    if questionnaire.pre_run:
        for prerun in questionnaire.pre_run:
            prerun_time = start_datetime + timedelta(minutes=prerun.time_before_start_min)
            _add_vertical_line(
                fig=fig,
                datetime_instance=prerun_time,
                color=SANDY,
                name="Pre-Run Nutrition",
                dash="dash",
                width=2.0,
                opacity=0.9,
            )
            _add_event_band(fig=fig, start_time=prerun_time, color=SANDY, width_minutes=1.0)

    if questionnaire.fueling_during_run:
        for fuel_instance, fuel in enumerate(questionnaire.fueling_during_run):
            fuel_time_diff = fuel.time_during_run_min
            fuel_time = start_datetime + timedelta(minutes=fuel_time_diff)
            _add_vertical_line(
                fig=fig,
                datetime_instance=fuel_time,
                color=NAVY,
                name=f"Fueling {int(fuel_instance) + 1}",
                dash="dot",
                width=1.8,
                opacity=0.85,
            )
            _add_event_band(fig=fig, start_time=fuel_time, color=NAVY, width_minutes=1.0)

    layout = get_default_layout(
        title="Single Activity CareLink Overview",
        xaxis_title="",
        yaxis_title="Sensor Glucose [mg/dl]",
        height=420,
        showlegend=True,
    )
    layout["margin"] = {"l": 56, "r": 24, "t": 28, "b": 152}
    fig.update_layout(**layout, barmode="overlay", hovermode="x unified")
    fig.update_layout(
        legend=get_bottom_legend(y=-0.28) | {"tracegroupgap": 8, "x": 0.5, "xanchor": "center"},
    )

    return fig


def _add_event_band(*, fig: go.Figure, start_time: datetime, color: str, width_minutes: float) -> None:
    half_width = timedelta(minutes=width_minutes / 2)
    fig.add_vrect(
        x0=start_time - half_width,
        x1=start_time + half_width,
        fillcolor=color,
        opacity=0.12,
        line_width=0,
        layer="below",
    )


def _add_vertical_line(
    *,
    fig: go.Figure,
    datetime_instance: datetime,
    color: str,
    name: str,
    dash: str = "dash",
    width: float = 1.5,
    opacity: float = 1.0,
) -> None:
    fig.add_trace(
        go.Scatter(
            x=[datetime_instance, datetime_instance],
            y=[70, 250],
            mode="lines",
            name=name,
            line=dict(color=color, width=width, dash=dash),
            opacity=opacity,
        )
    )
