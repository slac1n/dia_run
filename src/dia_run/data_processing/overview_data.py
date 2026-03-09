from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from time import perf_counter

import polars as pl
from loguru import logger

from dia_run.data_models.kpis import KpiModel
from dia_run.data_models.paths import DataPaths
from dia_run.data_processing.data_processing import DataProcessor


def get_data_paths_key(*, data_paths: DataPaths) -> tuple[str, ...]:
    return (
        str(data_paths.strava_summary.resolve()),
        str(data_paths.strava_stream.resolve()),
        str(data_paths.carelink.resolve()),
        str(data_paths.questionnaire.resolve()),
    )


@dataclass(frozen=True)
class DashboardOverviewData:
    summary: pl.DataFrame
    kpis: KpiModel
    pending_questionnaires: int
    data_processor: DataProcessor


class OverviewDataService:
    def __init__(self, *, data_paths: DataPaths) -> None:
        self.data_paths = data_paths
        self._lock = Lock()
        self._generation = 0
        self._cached_generation: int | None = None
        self._cached_date: str | None = None
        self._cached_data: DashboardOverviewData | None = None

    def get_dashboard_data(self) -> DashboardOverviewData:
        reference_datetime = datetime.now()
        today = reference_datetime.date().isoformat()

        with self._lock:
            if (
                self._cached_data is not None
                and self._cached_generation == self._generation
                and self._cached_date == today
            ):
                logger.debug("Serving cached dashboard data for data root {}", self.data_paths.data_root)
                return self._cached_data
            generation_snapshot = self._generation

        dashboard_data = self._build_dashboard_data(reference_datetime=reference_datetime)

        with self._lock:
            if self._generation == generation_snapshot:
                self._cached_generation = generation_snapshot
                self._cached_date = today
                self._cached_data = dashboard_data

        return dashboard_data

    def invalidate(self) -> None:
        with self._lock:
            self._generation += 1
            self._cached_generation = None
            self._cached_date = None
            self._cached_data = None

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
            data_processor=data_processor,
        )


_OVERVIEW_DATA_SERVICES: dict[tuple[str, ...], OverviewDataService] = {}
_OVERVIEW_DATA_SERVICES_LOCK = Lock()


def get_overview_data_service(*, data_paths: DataPaths) -> OverviewDataService:
    service_key = get_data_paths_key(data_paths=data_paths)
    with _OVERVIEW_DATA_SERVICES_LOCK:
        if service_key not in _OVERVIEW_DATA_SERVICES:
            _OVERVIEW_DATA_SERVICES[service_key] = OverviewDataService(data_paths=data_paths)
        return _OVERVIEW_DATA_SERVICES[service_key]


def invalidate_overview_data_service(*, data_paths: DataPaths) -> None:
    service_key = get_data_paths_key(data_paths=data_paths)
    with _OVERVIEW_DATA_SERVICES_LOCK:
        service = _OVERVIEW_DATA_SERVICES.get(service_key)

    if service is not None:
        service.invalidate()
