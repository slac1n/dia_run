from pathlib import Path

from loguru import logger

from dia_run.data_fetcher.fetcher_protocol import DataFetcherService
from dia_run.data_fetcher.live_fetcher import LiveDataFetcher
from dia_run.data_fetcher.mock_fetcher import MockDataFetcher
from dia_run.data_fetcher.questionnaire import RunFuelQuestionnaire
from dia_run.data_models.paths import DataPaths
from dia_run.s3_sync import S3DataSync
from dia_run.settings import settings

MOCK_DATA_ROOT = Path("mock-data")


def run_fetcher() -> None:
    data_paths: DataPaths
    if settings.use_mock_data:
        logger.info("[MOCK] CLI running in mock data mode — no real API calls will be made")
        data_paths = DataPaths.from_root(root=MOCK_DATA_ROOT)
    else:
        data_paths = DataPaths.from_root(root=settings.data_root)

    sync_service = S3DataSync(data_paths=data_paths)
    sync_service.sync_from_s3_on_startup()

    data_fetcher: DataFetcherService
    if settings.use_mock_data:
        data_fetcher = MockDataFetcher(data_paths=data_paths)
    else:
        data_fetcher = LiveDataFetcher(data_paths=data_paths)

    data_fetcher.fetch_latest_data_and_save()
    sync_service.sync_to_s3_after_fetch()

    questionnaire = RunFuelQuestionnaire(data_paths=data_paths)
    questionnaire.ask_me()
    sync_service.sync_to_s3_after_questionnaire()
