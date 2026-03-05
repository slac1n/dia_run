from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import RedirectResponse
from loguru import logger

from dia_run.data_fetcher.fetcher_protocol import DataFetcherService
from dia_run.web.dependencies import get_data_fetcher_service
from dia_run.web.fetch_status import set_fetch_status

router = APIRouter()


def _fetch_data_task(*, fetcher: DataFetcherService) -> None:
    set_fetch_status(status="started")
    try:
        fetcher.fetch_latest_data_and_save()
        set_fetch_status(status="success")
    except ValueError as exc:
        logger.error("Data fetch failed: {error}", error=str(exc))
        set_fetch_status(status="error")


@router.post("/fetch")
def fetch_new_data(
    *,
    background_tasks: BackgroundTasks,
    fetcher: Annotated[DataFetcherService, Depends(get_data_fetcher_service)],
) -> RedirectResponse:
    background_tasks.add_task(_fetch_data_task, fetcher=fetcher)
    return RedirectResponse(url="/questionnaire?fetch=started", status_code=303)
