from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock
from time import perf_counter

import polars as pl
from loguru import logger

from dia_run.data_models.kpis import KpiModel
from dia_run.data_models.paths import DataPaths
from dia_run.data_processing.data_processing import DataProcessor


@dataclass(frozen=True)
class DashboardOverviewData:
    summary: pl.DataFrame
    kpis: KpiModel
    pending_questionnaires: int


class OverviewDataService:
    def __init__(self, *, data_paths: DataPaths) -> None:
        self.data_paths = data_paths
        self._cache_lock = Lock()
        self._cache_generation = 0
        self._cached_key: tuple[object, ...] | None = None
        self._cached_data: DashboardOverviewData | None = None

    def get_dashboard_data(self) -> DashboardOverviewData:
        reference_datetime = datetime.now()
        cache_key = self._build_cache_key(reference_datetime=reference_datetime)

        with self._cache_lock:
            if self._cached_key == cache_key and self._cached_data is not None:
                logger.debug("Serving cached dashboard data for data root {}", self.data_paths.data_root)
                return self._cached_data

            dashboard_data = self._build_dashboard_data(reference_datetime=reference_datetime)
            self._cached_key = cache_key
            self._cached_data = dashboard_data
            return dashboard_data

    def invalidate(self) -> None:
        with self._cache_lock:
            self._cache_generation += 1
            self._cached_key = None
            self._cached_data = None

    def _build_cache_key(self, *, reference_datetime: datetime) -> tuple[object, ...]:
        return (
            self._cache_generation,
            reference_datetime.date().isoformat(),
            self._get_delta_log_signature(path=self.data_paths.strava_summary),
            self._get_delta_log_signature(path=self.data_paths.strava_stream),
            self._get_delta_log_signature(path=self.data_paths.carelink),
            self._get_directory_signature(path=self.data_paths.questionnaire),
        )

    def _build_dashboard_data(self, *, reference_datetime: datetime) -> DashboardOverviewData:
        build_started = perf_counter()
        data_processor = DataProcessor(data_paths=self.data_paths)

        summary = data_processor.get_summary()
        kpis = data_processor.get_30_day_kpis(reference_date=reference_datetime)
        pending_questionnaires = data_processor.get_pending_questionnaire_count()

        elapsed_ms = (perf_counter() - build_started) * 1000
        logger.info("Dashboard overview data cache refreshed in {:.1f} ms", elapsed_ms)

        return DashboardOverviewData(
            summary=summary,
            kpis=kpis,
            pending_questionnaires=pending_questionnaires,
        )

    def _get_delta_log_signature(self, *, path: Path) -> tuple[int, int]:
        return self._get_directory_signature(path=path / "_delta_log")

    def _get_directory_signature(self, *, path: Path) -> tuple[int, int]:
        if not path.exists():
            return (0, 0)

        latest_mtime_ns = path.stat().st_mtime_ns
        file_count = 0
        for child in path.rglob("*"):
            if not child.is_file():
                continue

            child_stat = child.stat()
            file_count += 1
            latest_mtime_ns = max(latest_mtime_ns, child_stat.st_mtime_ns)

        return (file_count, latest_mtime_ns)


_OVERVIEW_DATA_SERVICES: dict[tuple[str, ...], OverviewDataService] = {}
_OVERVIEW_DATA_SERVICES_LOCK = Lock()


def get_overview_data_service(*, data_paths: DataPaths) -> OverviewDataService:
    service_key = _get_service_key(data_paths=data_paths)
    with _OVERVIEW_DATA_SERVICES_LOCK:
        if service_key not in _OVERVIEW_DATA_SERVICES:
            _OVERVIEW_DATA_SERVICES[service_key] = OverviewDataService(data_paths=data_paths)
        return _OVERVIEW_DATA_SERVICES[service_key]


def invalidate_overview_data_service(*, data_paths: DataPaths) -> None:
    service_key = _get_service_key(data_paths=data_paths)
    with _OVERVIEW_DATA_SERVICES_LOCK:
        service = _OVERVIEW_DATA_SERVICES.get(service_key)

    if service is not None:
        service.invalidate()


def _get_service_key(*, data_paths: DataPaths) -> tuple[str, ...]:
    return (
        str(data_paths.strava_summary.resolve()),
        str(data_paths.strava_stream.resolve()),
        str(data_paths.carelink.resolve()),
        str(data_paths.questionnaire.resolve()),
    )
