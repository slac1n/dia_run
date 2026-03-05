from pathlib import Path

from loguru import logger

from dia_run.data_fetcher.fetcher_protocol import DataFetcherService
from dia_run.data_fetcher.live_fetcher import LiveDataFetcher
from dia_run.data_fetcher.mock_fetcher import MockDataFetcher
from dia_run.data_fetcher.questionnaire import RunFuelQuestionnaire
from dia_run.data_models.paths import DataPaths
from dia_run.settings import settings

MOCK_DATA_ROOT = Path("mock-data")


def run_fetcher() -> None:
    data_fetcher: DataFetcherService
    if settings.use_mock_data:
        logger.info("[MOCK] CLI running in mock data mode — no real API calls will be made")
        data_paths = DataPaths(
            strava_summary=MOCK_DATA_ROOT / "strava" / "summary",
            strava_stream=MOCK_DATA_ROOT / "strava" / "stream",
            carelink=MOCK_DATA_ROOT / "carelink",
            questionnaire=MOCK_DATA_ROOT / "run_questionnaires",
        )
        data_fetcher = MockDataFetcher(data_paths=data_paths)
    else:
        data_paths = DataPaths()
        data_fetcher = LiveDataFetcher(data_paths=data_paths)

    data_fetcher.fetch_latest_data_and_save()

    questionnaire = RunFuelQuestionnaire(data_paths=data_paths)
    questionnaire.ask_me()
