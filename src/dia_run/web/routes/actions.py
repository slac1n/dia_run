from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import RedirectResponse
from loguru import logger

from dia_run.data_fetcher.data_fetcher import DataFetcher
from dia_run.data_models.paths import DataPaths
from dia_run.web.dependencies import get_data_paths

router = APIRouter()


@router.post("/fetch")
def _run_fetch(*, data_paths: DataPaths) -> None:
    data_fetcher = DataFetcher(data_paths=data_paths)
    try:
        data_fetcher.fetch_latest_data_and_save()
    except ValueError as exc:
        logger.error("Data fetch failed: {error}", error=str(exc))


@router.post("/fetch")
def fetch_new_data(
    *,
    background_tasks: BackgroundTasks,
    data_paths: Annotated[DataPaths, Depends(get_data_paths)],
) -> RedirectResponse:
    background_tasks.add_task(_run_fetch, data_paths=data_paths)
    return RedirectResponse(url="/?fetch=started", status_code=303)
