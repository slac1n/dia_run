from typing import Annotated
from urllib.parse import unquote

import polars as pl
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from dia_run.dashboard.charts.activity_calendar import create_activity_calendar_chart
from dia_run.dashboard.charts.basal_adjustment_impact import (
    create_basal_adjustment_tir_chart,
)
from dia_run.dashboard.charts.diabetes_management import (
    create_in_going_out_going_sensor_glucose_chart,
    create_insulin_on_board_and_normalized_glucose_change_chart,
    create_pre_nutrition_bolus_chart,
    create_pre_nutrition_heatmap,
    create_pre_nutrition_impact_chart,
    create_pre_nutrition_timing_chart,
)
from dia_run.dashboard.charts.fueling_impact import (
    create_fueling_carbs_vs_peak_chart,
    create_fueling_glucose_response_chart,
)
from dia_run.dashboard.charts.run_types import (
    create_run_type_distance_chart,
    create_run_type_glucose_chart,
    create_run_type_heartrate_chart,
    create_run_type_pie_chart,
)
from dia_run.data_models.run_types import RunType
from dia_run.data_processing.data_processing import DataProcessor
from dia_run.web.dependencies import get_data_processor
from dia_run.web.plotly_embed import PLOTLY_CDN, render_plotly_figure
from dia_run.web.templates import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    *,
    data_processor: Annotated[DataProcessor, Depends(get_data_processor)],
) -> HTMLResponse:
    df_summary = data_processor.get_summary()
    kpis = data_processor.get_30_day_kpis()
    data_paths = data_processor.data_paths

    fetch_status = request.query_params.get("fetch")
    message_param = request.query_params.get("message")
    message_text = unquote(message_param) if message_param else None
    if fetch_status == "success":
        flash = {
            "level": "success",
            "message": message_text or "New data downloaded successfully.",
        }
    elif fetch_status == "started":
        flash = {
            "level": "success",
            "message": "Data fetch started. Check back in a few minutes for updates.",
        }
    elif fetch_status == "error":
        flash = {
            "level": "error",
            "message": message_text or "Data fetch failed. Check the logs for details.",
        }
    else:
        flash = None

    data_paths.questionnaire.mkdir(parents=True, exist_ok=True)
    existing_ids = {int(path.stem) for path in data_paths.questionnaire.glob("*.json") if path.stem.isdigit()}
    if existing_ids:
        pending_count = len(df_summary.filter(~pl.col("activity_id").is_in(list(existing_ids))))
    else:
        pending_count = len(df_summary)

    kpi_cards = [
        {"label": "Total Distance", "value": f"{kpis.total_distance_km:.1f} km"},
        {"label": "Total Running Time", "value": kpis.formatted_running_time},
        {
            "label": "Avg Sensor Glucose",
            "value": (f"{kpis.avg_sensor_glucose:.0f} mg/dL" if kpis.avg_sensor_glucose is not None else "N/A"),
        },
        {
            "label": "Time in Range",
            "value": (f"{kpis.time_in_range_percentage:.0f}%" if kpis.time_in_range_percentage is not None else "N/A"),
        },
    ]

    run_type_order = [RunType.EASY, RunType.INTERVAL, RunType.TEMPO, RunType.LONG, RunType.RACE]

    charts = {
        "activity_calendar": render_plotly_figure(
            figure=create_activity_calendar_chart(df_summary),
        ),
        "run_type_pie": render_plotly_figure(
            figure=create_run_type_pie_chart(data_processor=data_processor, run_type_order=run_type_order),
        ),
        "run_type_distance": render_plotly_figure(
            figure=create_run_type_distance_chart(data_processor=data_processor, run_type_order=run_type_order),
        ),
        "run_type_heartrate": render_plotly_figure(
            figure=create_run_type_heartrate_chart(data_processor=data_processor, run_type_order=run_type_order),
        ),
        "run_type_glucose": render_plotly_figure(
            figure=create_run_type_glucose_chart(data_processor=data_processor, run_type_order=run_type_order),
        ),
        "in_out_sg": render_plotly_figure(
            figure=create_in_going_out_going_sensor_glucose_chart(data_processor=data_processor),
        ),
        "iob_norm_change": render_plotly_figure(
            figure=create_insulin_on_board_and_normalized_glucose_change_chart(data_processor),
        ),
        "pre_nutrition_impact": render_plotly_figure(
            figure=create_pre_nutrition_impact_chart(data_processor),
        ),
        "pre_nutrition_bolus": render_plotly_figure(
            figure=create_pre_nutrition_bolus_chart(data_processor),
        ),
        "pre_nutrition_timing": render_plotly_figure(
            figure=create_pre_nutrition_timing_chart(data_processor),
        ),
        "pre_nutrition_heatmap": render_plotly_figure(
            figure=create_pre_nutrition_heatmap(data_processor),
        ),
        "fueling_response": render_plotly_figure(
            figure=create_fueling_glucose_response_chart(data_processor=data_processor),
        ),
        "fueling_carbs_peak": render_plotly_figure(
            figure=create_fueling_carbs_vs_peak_chart(data_processor=data_processor),
        ),
        "basal_adjustment_tir": render_plotly_figure(
            figure=create_basal_adjustment_tir_chart(data_processor=data_processor),
        ),
    }

    nav_items = [
        {"label": "Overview", "href": "#overview"},
        {"label": "Activities", "href": "#activities"},
        {"label": "Run Types", "href": "#run-types"},
        {"label": "Diabetes", "href": "#diabetes"},
        {"label": "Fueling", "href": "#fueling"},
    ]

    return templates.TemplateResponse(
        request,
        "pages/dashboard.html",
        {
            "request": request,
            "title": "Dia-Run Dashboard",
            "plotly_cdn": PLOTLY_CDN,
            "nav_items": nav_items,
            "kpi_cards": kpi_cards,
            "flash": flash,
            "charts": charts,
            "pending_questionnaires": pending_count,
        },
    )
