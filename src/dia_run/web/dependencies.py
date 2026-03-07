from pathlib import Path
from typing import Annotated

from fastapi import Depends
from loguru import logger

from dia_run.data_fetcher.fetcher_protocol import DataFetcherService
from dia_run.data_fetcher.live_fetcher import LiveDataFetcher
from dia_run.data_fetcher.mock_fetcher import MockDataFetcher
from dia_run.data_models.paths import DataPaths
from dia_run.data_processing.data_processing import DataProcessor
from dia_run.s3_sync import S3DataSync
from dia_run.settings import settings

MOCK_DATA_ROOT = Path("mock-data")


def get_data_paths() -> DataPaths:
    if settings.use_mock_data:
        logger.info("[MOCK] Using mock data paths from ./mock-data/")
        return DataPaths.from_root(root=MOCK_DATA_ROOT)
    return DataPaths.from_root(root=settings.data_root)


def get_data_processor(*, data_paths: Annotated[DataPaths, Depends(get_data_paths)]) -> DataProcessor:
    return DataProcessor(data_paths=data_paths)


def get_data_fetcher_service(*, data_paths: Annotated[DataPaths, Depends(get_data_paths)]) -> DataFetcherService:
    if settings.use_mock_data:
        logger.info("[MOCK] Using MockDataFetcher — no real API calls will be made")
        return MockDataFetcher(data_paths=data_paths)
    return LiveDataFetcher(data_paths=data_paths)


def get_s3_sync_service(*, data_paths: Annotated[DataPaths, Depends(get_data_paths)]) -> S3DataSync:
    return S3DataSync(data_paths=data_paths)
