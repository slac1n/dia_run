import json
from collections.abc import Mapping, Sequence
from itertools import zip_longest
from typing import Annotated, cast

import polars as pl
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from loguru import logger
from pydantic import ValidationError

from dia_run.data_models.questionnaire import QuestionnaireModel
from dia_run.data_processing.data_processing import DataProcessor
from dia_run.data_processing.overview_data import invalidate_overview_data_service
from dia_run.s3_sync import S3DataSync
from dia_run.web.dependencies import get_data_processor, get_s3_sync_service
from dia_run.web.fetch_status import FetchState, get_fetch_status
from dia_run.web.services.overview_page import invalidate_overview_page_service
from dia_run.web.templates import templates

router = APIRouter(prefix="/questionnaire")


def _format_validation_errors(*, errors: Sequence[Mapping[str, object]]) -> list[str]:
    formatted: list[str] = []
    for error in errors:
        loc_value = error.get("loc")
        if isinstance(loc_value, (list, tuple)):
            loc_parts = cast(Sequence[object], loc_value)
            loc = " -> ".join(str(part) for part in loc_parts)
        else:
            loc = ""
        msg = str(error.get("msg", "Invalid value"))
        formatted.append(f"{loc}: {msg}" if loc else msg)
    return formatted


def _get_unannotated_activities(*, data_processor: DataProcessor) -> pl.DataFrame:
    data_paths = data_processor.data_paths
    data_paths.questionnaire.mkdir(parents=True, exist_ok=True)
    df_summary = data_processor.get_summary()

    existing_ids = {int(path.stem) for path in data_paths.questionnaire.glob("*.json") if path.stem.isdigit()}
    if existing_ids:
        return df_summary.filter(~pl.col("activity_id").is_in(list(existing_ids)))
    return df_summary


@router.get("", response_class=HTMLResponse)
def questionnaire_list(
    request: Request,
    *,
    data_processor: Annotated[DataProcessor, Depends(get_data_processor)],
) -> HTMLResponse:
    df_unannotated = _get_unannotated_activities(data_processor=data_processor)

    activities: list[dict[str, str | int]] = []
    for row in df_unannotated.sort("start_date_local", descending=True).iter_rows(named=True):
        activities.append(
            {
                "activity_id": row["activity_id"],
                "name": row["name"],
                "date": row["date"],
                "distance": f"{row['distance_in_km']} km",
                "run_type": str(row["run_type"]),
            }
        )

    page_links = [
        {"label": "Dashboard", "href": "/"},
        {"label": "Activities", "href": "/activities"},
        {"label": "Questionnaire", "href": "/questionnaire"},
    ]

    fetch_status = request.query_params.get("fetch")
    if fetch_status == "started":
        flash = {
            "level": "info",
            "message": "Data fetch started. New activities will appear below when ready.",
        }
    elif fetch_status == "success":
        flash = {
            "level": "success",
            "message": "New data downloaded! Please fill out the questionnaire for your new run(s).",
        }
    elif fetch_status == "no-new":
        flash = {
            "level": "info",
            "message": "Data checked. No new activities found.",
        }
    elif fetch_status == "error":
        flash = {
            "level": "error",
            "message": "Data fetch failed. Check the logs for details.",
        }
    elif fetch_status == "stale":
        flash = {
            "level": "error",
            "message": "CareLink data is out of date. Please retry later.",
        }
    else:
        flash = None

    return templates.TemplateResponse(
        request,
        "pages/questionnaire_list.html",
        {
            "request": request,
            "title": "Questionnaire",
            "page_links": page_links,
            "activities": activities,
            "activity_count": len(activities),
            "flash": flash,
            "auto_refresh": fetch_status == "started",
        },
    )


@router.get("/status")
def questionnaire_status() -> FetchState:
    return get_fetch_status()


@router.get("/{activity_id}", response_class=HTMLResponse)
def questionnaire_form(
    request: Request,
    *,
    activity_id: int,
    data_processor: Annotated[DataProcessor, Depends(get_data_processor)],
) -> HTMLResponse:
    data_paths = data_processor.data_paths
    df_summary = data_processor.get_summary()
    activity_df = df_summary.filter(pl.col("activity_id") == activity_id)
    if activity_df.is_empty():
        raise HTTPException(status_code=404, detail="Activity not found")

    row = activity_df.row(0, named=True)
    activity = {
        "activity_id": row["activity_id"],
        "name": row["name"],
        "date": row["date"],
        "distance": f"{row['distance_in_km']} km",
        "time": row["human_readable_time"],
        "run_type": str(row["run_type"]),
    }

    questionnaire_path = data_paths.questionnaire / f"{activity_id}.json"
    existing = questionnaire_path.exists()

    page_links = [
        {"label": "Dashboard", "href": "/"},
        {"label": "Activities", "href": "/activities"},
        {"label": "Questionnaire", "href": "/questionnaire"},
    ]

    return templates.TemplateResponse(
        request,
        "pages/questionnaire_form.html",
        {
            "request": request,
            "title": "Run Questionnaire",
            "page_links": page_links,
            "activity": activity,
            "existing": existing,
            "errors": [],
        },
    )


def _sync_questionnaire_to_s3(*, sync_service: S3DataSync) -> None:
    try:
        sync_service.sync_to_s3_after_questionnaire()
    except ValueError as exc:
        logger.error("S3 sync after questionnaire failed: {error}", error=str(exc))


@router.post("/{activity_id}", response_class=HTMLResponse, response_model=None)
async def submit_questionnaire(
    request: Request,
    *,
    activity_id: int,
    background_tasks: BackgroundTasks,
    data_processor: Annotated[DataProcessor, Depends(get_data_processor)],
    sync_service: Annotated[S3DataSync, Depends(get_s3_sync_service)],
) -> HTMLResponse | RedirectResponse:
    data_paths = data_processor.data_paths
    data_paths.questionnaire.mkdir(parents=True, exist_ok=True)
    df_summary = data_processor.get_summary()
    activity_df = df_summary.filter(pl.col("activity_id") == activity_id)
    if activity_df.is_empty():
        raise HTTPException(status_code=404, detail="Activity not found")

    row = activity_df.row(0, named=True)
    activity = {
        "activity_id": row["activity_id"],
        "name": row["name"],
        "date": row["date"],
        "distance": f"{row['distance_in_km']} km",
        "time": row["human_readable_time"],
        "run_type": str(row["run_type"]),
    }

    questionnaire_path = data_paths.questionnaire / f"{activity_id}.json"
    existing = questionnaire_path.exists()

    form = await request.form()

    pre_run_entries = []
    for carbs, timing, bolus, food in zip_longest(
        form.getlist("pre_run_carbohydrates_g"),
        form.getlist("pre_run_time_before_start_min"),
        form.getlist("pre_run_bolus_percentage"),
        form.getlist("pre_run_food_type"),
        fillvalue="",
    ):
        if not any([carbs, timing, bolus, food]):
            continue
        pre_run_entries.append(
            {
                "carbohydrates_g": carbs,
                "time_before_start_min": timing,
                "bolus_percentage": bolus,
                "food_type": food or None,
            }
        )

    basal_entries = []
    for adjustment_type, start_time, end_time, basal_percentage in zip_longest(
        form.getlist("basal_type"),
        form.getlist("basal_start_time_min"),
        form.getlist("basal_end_time_min"),
        form.getlist("basal_rate_percentage"),
        fillvalue="",
    ):
        if not any([adjustment_type, start_time, end_time, basal_percentage]):
            continue
        basal_entries.append(
            {
                "type": adjustment_type or None,
                "start_time_min": start_time,
                "end_time_min": end_time,
                "basal_rate_percentage": basal_percentage or None,
            }
        )

    fueling_entries = []
    for carbs, timing, food in zip_longest(
        form.getlist("fueling_carbohydrates_g"),
        form.getlist("fueling_time_during_run_min"),
        form.getlist("fueling_food_type"),
        fillvalue="",
    ):
        if not any([carbs, timing, food]):
            continue
        fueling_entries.append(
            {
                "carbohydrates_g": carbs,
                "time_during_run_min": timing,
                "food_type": food or None,
            }
        )

    bolus_entries = []
    for time_of_bolus, bolus_units in zip_longest(
        form.getlist("bolus_time_of_bolus_min"),
        form.getlist("bolus_units"),
        fillvalue="",
    ):
        if not any([time_of_bolus, bolus_units]):
            continue
        bolus_entries.append(
            {
                "time_of_bolus_min": time_of_bolus,
                "bolus_units": bolus_units,
            }
        )

    try:
        questionnaire = QuestionnaireModel(
            pre_run=pre_run_entries,
            basal_adjustments=basal_entries,
            fueling_during_run=fueling_entries,
            bolus=bolus_entries,
        )
    except ValidationError as exc:
        errors = _format_validation_errors(errors=cast(Sequence[Mapping[str, object]], exc.errors()))
        page_links = [
            {"label": "Dashboard", "href": "/"},
            {"label": "Activities", "href": "/activities"},
            {"label": "Questionnaire", "href": "/questionnaire"},
        ]
        return templates.TemplateResponse(
            request,
            "pages/questionnaire_form.html",
            {
                "request": request,
                "title": "Run Questionnaire",
                "page_links": page_links,
                "activity": activity,
                "existing": existing,
                "errors": errors,
            },
            status_code=422,
        )

    with open(questionnaire_path, "w") as f:
        json.dump(questionnaire.model_dump(mode="json"), f, indent=2)

    invalidate_overview_data_service(data_paths=data_paths)
    invalidate_overview_page_service(data_paths=data_paths)
    background_tasks.add_task(_sync_questionnaire_to_s3, sync_service=sync_service)

    return RedirectResponse(url=f"/activities/{activity_id}", status_code=303)
