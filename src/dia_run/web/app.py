import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from dia_run.data_processing.overview_data import invalidate_overview_data_service
from dia_run.s3_sync import S3DataSync
from dia_run.web.dependencies import get_data_paths
from dia_run.web.routes import actions, activities, coach, health, home, questionnaire
from dia_run.web.services.overview_page import invalidate_overview_page_service

WEB_ROOT = Path(__file__).resolve().parent
STATIC_DIR = WEB_ROOT / "static"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    data_paths = get_data_paths()
    sync_service = S3DataSync(data_paths=data_paths)
    await asyncio.to_thread(sync_service.sync_from_s3_on_startup)
    invalidate_overview_data_service(data_paths=data_paths)
    invalidate_overview_page_service(data_paths=data_paths)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Dia-Run", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(home.router)
    app.include_router(actions.router)
    app.include_router(activities.router)
    app.include_router(questionnaire.router)
    app.include_router(health.router)
    app.include_router(coach.router)
    return app


app = create_app()
