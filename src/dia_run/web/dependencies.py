from typing import Annotated

from fastapi import Depends

from dia_run.data_models.paths import DataPaths
from dia_run.data_processing.data_processing import DataProcessor


def get_data_paths() -> DataPaths:
    return DataPaths()


def get_data_processor(*, data_paths: Annotated[DataPaths, Depends(get_data_paths)]) -> DataProcessor:
    return DataProcessor(data_paths=data_paths)
