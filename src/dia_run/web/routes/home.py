from typing import Annotated
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from dia_run.web.dependencies import get_overview_service
from dia_run.web.plotly_embed import PLOTLY_CDN
from dia_run.web.services.overview_page import OverviewPageService
from dia_run.web.templates import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    *,
    overview_service: Annotated[OverviewPageService, Depends(get_overview_service)],
) -> HTMLResponse:
    dashboard_context = overview_service.get_dashboard_context()

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
            "kpi_cards": dashboard_context.kpi_cards,
            "flash": flash,
            "charts": dashboard_context.charts,
            "pending_questionnaires": dashboard_context.pending_questionnaires,
        },
    )
