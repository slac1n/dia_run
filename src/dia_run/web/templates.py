from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from fastapi.templating import Jinja2Templates

from dia_run.settings import settings

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _get_app_version() -> str:
    try:
        return f"v{version('dia-run')}"
    except PackageNotFoundError:
        return "dev"


templates.env.globals["app_version"] = _get_app_version()


def _coach_available() -> bool:
    return settings.coach_enabled


templates.env.globals["coach_available"] = _coach_available
