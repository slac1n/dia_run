from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from loguru import logger

from dia_run.data_fetcher.data_fetcher import DataFetcher
from dia_run.data_models.paths import DataPaths
from dia_run.web.dependencies import get_data_paths

router = APIRouter()


@router.post("/fetch")
def fetch_new_data(*, data_paths: Annotated[DataPaths, Depends(get_data_paths)]) -> RedirectResponse:
    data_fetcher = DataFetcher(data_paths=data_paths)
    try:
        data_fetcher.fetch_latest_data_and_save()
    except ValueError as exc:
        logger.error("Data fetch failed: {error}", error=str(exc))
        message = quote(str(exc))
        return RedirectResponse(url=f"/?fetch=error&message={message}", status_code=303)

    return RedirectResponse(url="/?fetch=success", status_code=303)
