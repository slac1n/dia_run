from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import RedirectResponse
from loguru import logger

from dia_run.data_fetcher.fetcher_protocol import DataFetcherService
from dia_run.s3_sync import S3DataSync
from dia_run.web.dependencies import get_data_fetcher_service, get_s3_sync_service
from dia_run.web.fetch_status import set_fetch_status

router = APIRouter()


def _fetch_data_task(*, fetcher: DataFetcherService, sync_service: S3DataSync) -> None:
    set_fetch_status(status="started")
    try:
        fetcher.fetch_latest_data_and_save()
        sync_service.sync_to_s3_after_fetch()
        set_fetch_status(status="success")
    except ValueError as exc:
        logger.error("Data fetch failed: {error}", error=str(exc))
        set_fetch_status(status="error")


@router.post("/fetch")
def fetch_new_data(
    *,
    background_tasks: BackgroundTasks,
    fetcher: Annotated[DataFetcherService, Depends(get_data_fetcher_service)],
    sync_service: Annotated[S3DataSync, Depends(get_s3_sync_service)],
) -> RedirectResponse:
    background_tasks.add_task(_fetch_data_task, fetcher=fetcher, sync_service=sync_service)
    return RedirectResponse(url="/questionnaire?fetch=started", status_code=303)
