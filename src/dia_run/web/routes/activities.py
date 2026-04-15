from typing import Annotated

import polars as pl
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from dia_run.dashboard.charts.single_activity import create_single_activity_carelink_chart
from dia_run.data_processing.data_processing import DataProcessor
from dia_run.web.dependencies import get_data_processor
from dia_run.web.plotly_embed import PLOTLY_CDN, render_plotly_figure
from dia_run.web.templates import templates

router = APIRouter(prefix="/activities")


@router.get("", response_class=HTMLResponse)
def list_activities(
    request: Request,
    *,
    data_processor: Annotated[DataProcessor, Depends(get_data_processor)],
) -> HTMLResponse:
    df_summary = data_processor.get_summary()
    df_sorted = df_summary.sort("start_date_local", descending=True)

    activities: list[dict[str, str | int]] = []
    for row in df_sorted.iter_rows(named=True):
        average_heartrate = row.get("average_heartrate")
        avg_sg = row.get("avg_sg")
        tir_pct = row.get("tir_pct")
        activities.append(
            {
                "activity_id": row["activity_id"],
                "name": row["name"],
                "date": row["date"],
                "distance": f"{row['distance_in_km']} km",
                "time": row["human_readable_time"],
                "pace": row["human_readable_pace"],
                "average_heartrate": (f"{average_heartrate:.0f} bpm" if average_heartrate is not None else "N/A"),
                "avg_glucose": f"{avg_sg:.0f} mg/dL" if avg_sg is not None else "\u2014",
                "time_in_range": f"{tir_pct:.0f}%" if tir_pct is not None else "\u2014",
                "run_type": str(row["run_type"]),
            }
        )

    page_links = [
        {"label": "Dashboard", "href": "/"},
    ]

    return templates.TemplateResponse(
        request,
        "pages/activities.html",
        {
            "request": request,
            "title": "Activities",
            "page_links": page_links,
            "activities": activities,
            "activity_count": len(activities),
        },
    )


@router.get("/{activity_id}", response_class=HTMLResponse)
def activity_detail(
    request: Request,
    *,
    activity_id: int,
    data_processor: Annotated[DataProcessor, Depends(get_data_processor)],
) -> HTMLResponse:
    df_summary = data_processor.get_summary()
    activity_df = df_summary.filter(pl.col("activity_id") == activity_id)
    if activity_df.is_empty():
        raise HTTPException(status_code=404, detail="Activity not found")

    row = activity_df.row(0, named=True)
    average_heartrate = row.get("average_heartrate")
    avg_sg = row.get("avg_sg")
    tir_pct = row.get("tir_pct")

    activity = {
        "activity_id": row["activity_id"],
        "name": row["name"],
        "date": row["date"],
        "distance": f"{row['distance_in_km']} km",
        "time": row["human_readable_time"],
        "pace": row["human_readable_pace"],
        "average_heartrate": (f"{average_heartrate:.0f} bpm" if average_heartrate is not None else "N/A"),
        "avg_glucose": f"{avg_sg:.0f} mg/dL" if avg_sg is not None else "\u2014",
        "time_in_range": f"{tir_pct:.0f}%" if tir_pct is not None else "\u2014",
        "run_type": str(row["run_type"]),
    }

    chart = render_plotly_figure(
        figure=create_single_activity_carelink_chart(
            data_processor=data_processor,
            activity_id=activity_id,
        ),
    )

    questionnaire = data_processor.get_questionnaire(activity_id)
    pre_run = [
        {
            "carbohydrates_g": entry.carbohydrates_g,
            "food_type": entry.food_type,
            "bolus_percentage": entry.bolus_percentage,
            "time_before_start_min": entry.time_before_start_min,
        }
        for entry in questionnaire.pre_run
    ]
    fueling = [
        {
            "carbohydrates_g": entry.carbohydrates_g,
            "food_type": entry.food_type,
            "time_during_run_min": entry.time_during_run_min,
        }
        for entry in questionnaire.fueling_during_run
    ]

    page_links = [
        {"label": "Dashboard", "href": "/"},
        {"label": "Activities", "href": "/activities"},
    ]

    return templates.TemplateResponse(
        request,
        "pages/activity_detail.html",
        {
            "request": request,
            "title": f"Activity {activity['activity_id']}",
            "plotly_cdn": PLOTLY_CDN,
            "page_links": page_links,
            "activity": activity,
            "chart": chart,
            "pre_run": pre_run,
            "fueling": fueling,
        },
    )
