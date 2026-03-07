from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from dia_run.s3_sync import S3DataSync
from dia_run.web.dependencies import get_data_paths
from dia_run.web.routes import actions, activities, health, home, questionnaire

WEB_ROOT = Path(__file__).resolve().parent
STATIC_DIR = WEB_ROOT / "static"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    sync_service = S3DataSync(data_paths=get_data_paths())
    sync_service.sync_from_s3_on_startup()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Dia-Run", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(home.router)
    app.include_router(actions.router)
    app.include_router(activities.router)
    app.include_router(questionnaire.router)
    app.include_router(health.router)
    return app


app = create_app()
