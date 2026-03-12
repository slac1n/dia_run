from typing import Protocol

from dia_run.data_models.paths import DataPaths


class DataFetcherService(Protocol):
    """Protocol defining the interface for data fetching implementations.

    Both LiveDataFetcher and MockDataFetcher satisfy this protocol.
    """

    def __init__(self, *, data_paths: DataPaths) -> None: ...

    def fetch_latest_data_and_save(self) -> int: ...
