from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import RedirectResponse
from loguru import logger

from dia_run.data_fetcher.fetcher_protocol import DataFetcherService
from dia_run.data_models.paths import DataPaths
from dia_run.data_processing.overview_data import invalidate_overview_data_service
from dia_run.s3_sync import S3DataSync
from dia_run.web.dependencies import get_data_fetcher_service, get_data_paths, get_s3_sync_service
from dia_run.web.fetch_status import set_fetch_status
from dia_run.web.services.overview_page import invalidate_overview_page_service

router = APIRouter()


def _fetch_data_task(*, fetcher: DataFetcherService, sync_service: S3DataSync, data_paths: DataPaths) -> None:
    set_fetch_status(status="started")
    try:
        inserted_count = fetcher.fetch_latest_data_and_save()
        invalidate_overview_data_service(data_paths=data_paths)
        invalidate_overview_page_service(data_paths=data_paths)
        sync_service.sync_to_s3_after_fetch()
        set_fetch_status(status="success", inserted_count=inserted_count)
    except ValueError as exc:
        logger.error("Data fetch failed: {error}", error=str(exc))
        set_fetch_status(status="error")


@router.post("/fetch")
def fetch_new_data(
    *,
    background_tasks: BackgroundTasks,
    fetcher: Annotated[DataFetcherService, Depends(get_data_fetcher_service)],
    sync_service: Annotated[S3DataSync, Depends(get_s3_sync_service)],
    data_paths: Annotated[DataPaths, Depends(get_data_paths)],
) -> RedirectResponse:
    set_fetch_status(status="started")
    background_tasks.add_task(_fetch_data_task, fetcher=fetcher, sync_service=sync_service, data_paths=data_paths)
    return RedirectResponse(url="/questionnaire?fetch=started", status_code=303)
