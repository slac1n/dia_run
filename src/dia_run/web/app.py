from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from dia_run.web.routes import actions, activities, health, home, questionnaire

WEB_ROOT = Path(__file__).resolve().parent
STATIC_DIR = WEB_ROOT / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="Dia-Run")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(home.router)
    app.include_router(actions.router)
    app.include_router(activities.router)
    app.include_router(questionnaire.router)
    app.include_router(health.router)
    return app


app = create_app()
