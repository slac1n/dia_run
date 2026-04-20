"""Tests for OverviewDataService, OverviewPageService, and singleton registry helpers."""

from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from dia_run.data_models.kpis import KpiModel
from dia_run.data_models.paths import DataPaths
from dia_run.data_processing.overview_data import (
    DashboardOverviewData,
    OverviewDataService,
    get_data_paths_key,
    get_overview_data_service,
    invalidate_overview_data_service,
)
from dia_run.web.services.overview_page import (
    OverviewPageService,
    get_overview_page_service,
    invalidate_overview_page_service,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_data_paths(*, tmp_path_factory: pytest.TempPathFactory) -> DataPaths:
    root = tmp_path_factory.mktemp("overview")
    for sub in ("carelink", "strava/summary", "strava/stream", "questionnaire"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return DataPaths(
        carelink=root / "carelink",
        strava_summary=root / "strava" / "summary",
        strava_stream=root / "strava" / "stream",
        questionnaire=root / "questionnaire",
    )


def _stub_dashboard_data() -> DashboardOverviewData:
    return DashboardOverviewData(
        summary=pl.DataFrame({"a": [1]}),
        kpis=KpiModel(
            total_distance_km=10.0,
            total_running_time_minutes=60,
            avg_sensor_glucose=120.0,
            time_in_range_percentage=85.0,
        ),
        pending_questionnaires=0,
        data_processor=MagicMock(),
    )


# ---------------------------------------------------------------------------
# get_data_paths_key
# ---------------------------------------------------------------------------


class TestGetDataPathsKey:
    def test_returns_tuple_of_resolved_paths(self, *, tmp_path_factory: pytest.TempPathFactory) -> None:
        data_paths = _make_data_paths(tmp_path_factory=tmp_path_factory)
        key = get_data_paths_key(data_paths=data_paths)

        assert isinstance(key, tuple)
        assert len(key) == 4
        assert all(isinstance(p, str) for p in key)

    def test_same_paths_produce_same_key(self, *, tmp_path_factory: pytest.TempPathFactory) -> None:
        data_paths = _make_data_paths(tmp_path_factory=tmp_path_factory)
        key1 = get_data_paths_key(data_paths=data_paths)
        key2 = get_data_paths_key(data_paths=data_paths)
        assert key1 == key2

    def test_different_paths_produce_different_keys(self, *, tmp_path_factory: pytest.TempPathFactory) -> None:
        dp1 = _make_data_paths(tmp_path_factory=tmp_path_factory)
        dp2 = _make_data_paths(tmp_path_factory=tmp_path_factory)
        assert get_data_paths_key(data_paths=dp1) != get_data_paths_key(data_paths=dp2)


# ---------------------------------------------------------------------------
# OverviewDataService
# ---------------------------------------------------------------------------


class TestOverviewDataService:
    @pytest.fixture
    def data_paths(self, *, tmp_path_factory: pytest.TempPathFactory) -> DataPaths:
        return _make_data_paths(tmp_path_factory=tmp_path_factory)

    def test_get_dashboard_data_returns_dashboard_overview_data(self, *, data_paths: DataPaths) -> None:
        service = OverviewDataService(data_paths=data_paths)
        stub = _stub_dashboard_data()

        with patch.object(service, "_build_dashboard_data", return_value=stub):
            result = service.get_dashboard_data()

        assert result is stub

    def test_second_call_returns_cached_instance(self, *, data_paths: DataPaths) -> None:
        service = OverviewDataService(data_paths=data_paths)
        stub = _stub_dashboard_data()

        with patch.object(service, "_build_dashboard_data", return_value=stub) as build:
            first = service.get_dashboard_data()
            second = service.get_dashboard_data()

        assert first is second
        build.assert_called_once()

    def test_invalidate_causes_rebuild(self, *, data_paths: DataPaths) -> None:
        service = OverviewDataService(data_paths=data_paths)
        stub1 = _stub_dashboard_data()
        stub2 = _stub_dashboard_data()

        with patch.object(service, "_build_dashboard_data", side_effect=[stub1, stub2]) as build:
            first = service.get_dashboard_data()
            service.invalidate()
            second = service.get_dashboard_data()

        assert first is stub1
        assert second is stub2
        assert build.call_count == 2

    def test_invalidate_increments_generation(self, *, data_paths: DataPaths) -> None:
        service = OverviewDataService(data_paths=data_paths)
        assert service._generation == 0  # noqa: SLF001
        service.invalidate()
        assert service._generation == 1  # noqa: SLF001

    def test_invalidate_clears_cache(self, *, data_paths: DataPaths) -> None:
        service = OverviewDataService(data_paths=data_paths)
        stub = _stub_dashboard_data()

        with patch.object(service, "_build_dashboard_data", return_value=stub):
            service.get_dashboard_data()

        service.invalidate()
        assert service._cached_data is None  # noqa: SLF001
        assert service._cached_generation is None  # noqa: SLF001
        assert service._cached_date is None  # noqa: SLF001

    def test_build_dashboard_data_integration(self, *, test_data_paths: DataPaths) -> None:
        """Integration test using the session-scoped Delta Lake test data."""
        service = OverviewDataService(data_paths=test_data_paths)
        result = service.get_dashboard_data()

        assert isinstance(result, DashboardOverviewData)
        assert isinstance(result.summary, pl.DataFrame)
        assert len(result.summary) > 0
        assert isinstance(result.kpis, KpiModel)
        assert result.pending_questionnaires >= 0
        assert result.data_processor is not None


# ---------------------------------------------------------------------------
# OverviewPageService
# ---------------------------------------------------------------------------


class TestOverviewPageService:
    def test_get_dashboard_context_returns_context(self, *, test_data_paths: DataPaths) -> None:
        data_service = OverviewDataService(data_paths=test_data_paths)
        page_service = OverviewPageService(data_paths=test_data_paths, overview_data_service=data_service)

        context = page_service.get_dashboard_context()

        assert context.kpi_cards is not None
        assert len(context.kpi_cards) == 4
        assert isinstance(context.charts, dict)
        assert len(context.charts) > 0
        assert isinstance(context.pending_questionnaires, int)

    def test_second_call_returns_cached_context(self, *, test_data_paths: DataPaths) -> None:
        data_service = OverviewDataService(data_paths=test_data_paths)
        page_service = OverviewPageService(data_paths=test_data_paths, overview_data_service=data_service)

        first = page_service.get_dashboard_context()
        second = page_service.get_dashboard_context()
        assert first is second

    def test_invalidate_data_causes_page_rebuild(self, *, test_data_paths: DataPaths) -> None:
        data_service = OverviewDataService(data_paths=test_data_paths)
        page_service = OverviewPageService(data_paths=test_data_paths, overview_data_service=data_service)

        first = page_service.get_dashboard_context()
        data_service.invalidate()
        second = page_service.get_dashboard_context()

        # After data invalidation, the data service builds a new DashboardOverviewData
        # with a different identity, so the page service must rebuild.
        assert first is not second

    def test_page_invalidate_clears_cached_context(self, *, test_data_paths: DataPaths) -> None:
        data_service = OverviewDataService(data_paths=test_data_paths)
        page_service = OverviewPageService(data_paths=test_data_paths, overview_data_service=data_service)

        page_service.get_dashboard_context()
        page_service.invalidate()

        assert page_service._cached_context is None  # noqa: SLF001
        assert page_service._cached_dashboard_data is None  # noqa: SLF001

    def test_charts_contain_expected_keys(self, *, test_data_paths: DataPaths) -> None:
        data_service = OverviewDataService(data_paths=test_data_paths)
        page_service = OverviewPageService(data_paths=test_data_paths, overview_data_service=data_service)

        context = page_service.get_dashboard_context()
        expected_keys = {
            "activity_calendar",
            "run_type_pie",
            "run_type_distance",
            "run_type_heartrate",
            "run_type_glucose",
            "in_out_sg",
            "iob_norm_change",
            "pre_nutrition_impact",
            "pre_nutrition_bolus",
            "pre_nutrition_timing",
            "pre_nutrition_heatmap",
            "fueling_response",
            "fueling_carbs_peak",
            "fueling_timing_effect",
            "fueling_sg_effect",
            "basal_adjustment_tir",
            "time_of_day_outcomes",
            "first20_stability_effect",
            "basal_lead_time_effect",
            "sg20_predictor",
            "similar_runs_benchmark",
        }
        assert set(context.charts.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Singleton registry functions
# ---------------------------------------------------------------------------


class TestOverviewDataServiceRegistry:
    def test_get_returns_same_instance(self, *, tmp_path_factory: pytest.TempPathFactory) -> None:
        data_paths = _make_data_paths(tmp_path_factory=tmp_path_factory)
        svc1 = get_overview_data_service(data_paths=data_paths)
        svc2 = get_overview_data_service(data_paths=data_paths)
        assert svc1 is svc2

    def test_different_paths_return_different_instances(self, *, tmp_path_factory: pytest.TempPathFactory) -> None:
        dp1 = _make_data_paths(tmp_path_factory=tmp_path_factory)
        dp2 = _make_data_paths(tmp_path_factory=tmp_path_factory)
        assert get_overview_data_service(data_paths=dp1) is not get_overview_data_service(data_paths=dp2)

    def test_invalidate_calls_service_invalidate(self, *, tmp_path_factory: pytest.TempPathFactory) -> None:
        data_paths = _make_data_paths(tmp_path_factory=tmp_path_factory)
        svc = get_overview_data_service(data_paths=data_paths)

        with patch.object(svc, "invalidate") as mock_inv:
            invalidate_overview_data_service(data_paths=data_paths)
            mock_inv.assert_called_once()


class TestOverviewPageServiceRegistry:
    def test_get_returns_same_instance(self, *, tmp_path_factory: pytest.TempPathFactory) -> None:
        data_paths = _make_data_paths(tmp_path_factory=tmp_path_factory)
        svc1 = get_overview_page_service(data_paths=data_paths)
        svc2 = get_overview_page_service(data_paths=data_paths)
        assert svc1 is svc2

    def test_page_service_references_data_service_singleton(self, *, tmp_path_factory: pytest.TempPathFactory) -> None:
        data_paths = _make_data_paths(tmp_path_factory=tmp_path_factory)
        page_svc = get_overview_page_service(data_paths=data_paths)
        data_svc = get_overview_data_service(data_paths=data_paths)
        assert page_svc.overview_data_service is data_svc

    def test_invalidate_calls_service_invalidate(self, *, tmp_path_factory: pytest.TempPathFactory) -> None:
        data_paths = _make_data_paths(tmp_path_factory=tmp_path_factory)
        svc = get_overview_page_service(data_paths=data_paths)

        with patch.object(svc, "invalidate") as mock_inv:
            invalidate_overview_page_service(data_paths=data_paths)
            mock_inv.assert_called_once()
