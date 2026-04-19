from dataclasses import dataclass
from threading import Lock
from time import perf_counter

from loguru import logger
from markupsafe import Markup

from dia_run.dashboard.charts.activity_calendar import create_activity_calendar_chart
from dia_run.dashboard.charts.basal_adjustment_impact import create_basal_adjustment_tir_chart
from dia_run.dashboard.charts.diabetes_management import (
    create_in_going_out_going_sensor_glucose_chart,
    create_insulin_on_board_and_normalized_glucose_change_chart,
    create_pre_nutrition_bolus_chart,
    create_pre_nutrition_heatmap,
    create_pre_nutrition_impact_chart,
    create_pre_nutrition_timing_chart,
)
from dia_run.dashboard.charts.fueling_impact import (
    create_fueling_carbs_vs_peak_chart,
    create_fueling_glucose_response_chart,
)
from dia_run.dashboard.charts.pattern_insights import (
    create_basal_lead_time_effect_chart,
    create_first20_stability_effect_chart,
    create_sg20_predictor_chart,
    create_similar_runs_benchmark_chart,
    create_time_of_day_outcomes_chart,
    create_time_of_day_pre_run_profile_chart,
)
from dia_run.dashboard.charts.run_types import (
    create_run_type_distance_chart,
    create_run_type_glucose_chart,
    create_run_type_heartrate_chart,
    create_run_type_pie_chart,
)
from dia_run.data_models.paths import DataPaths
from dia_run.data_models.run_types import RunType
from dia_run.data_processing.data_processing import DataProcessor
from dia_run.data_processing.overview_data import (
    DashboardOverviewData,
    OverviewDataService,
    get_data_paths_key,
    get_overview_data_service,
)
from dia_run.web.plotly_embed import render_plotly_figure


@dataclass(frozen=True)
class DashboardOverviewContext:
    kpi_cards: list[dict[str, str]]
    charts: dict[str, Markup]
    pending_questionnaires: int


class OverviewPageService:
    def __init__(self, *, data_paths: DataPaths, overview_data_service: OverviewDataService) -> None:
        self.data_paths = data_paths
        self.overview_data_service = overview_data_service
        self._lock = Lock()
        self._cached_dashboard_data: DashboardOverviewData | None = None
        self._cached_context: DashboardOverviewContext | None = None

    def get_dashboard_context(self) -> DashboardOverviewContext:
        dashboard_data = self.overview_data_service.get_dashboard_data()

        with self._lock:
            if self._cached_dashboard_data is dashboard_data and self._cached_context is not None:
                logger.debug("Serving cached dashboard overview for data root {}", self.data_paths.data_root)
                return self._cached_context

        dashboard_context = self._build_dashboard_context(dashboard_data=dashboard_data)

        with self._lock:
            self._cached_dashboard_data = dashboard_data
            self._cached_context = dashboard_context

        return dashboard_context

    def invalidate(self) -> None:
        with self._lock:
            self._cached_dashboard_data = None
            self._cached_context = None

    def _build_dashboard_context(self, *, dashboard_data: DashboardOverviewData) -> DashboardOverviewContext:
        build_started = perf_counter()

        charts = self._build_charts(data_processor=dashboard_data.data_processor, dashboard_data=dashboard_data)

        elapsed_ms = (perf_counter() - build_started) * 1000
        logger.info("Dashboard overview page cache refreshed in {:.1f} ms", elapsed_ms)

        kpis = dashboard_data.kpis
        return DashboardOverviewContext(
            kpi_cards=[
                {"label": "Total Distance", "value": f"{kpis.total_distance_km:.1f} km"},
                {"label": "Total Running Time", "value": kpis.formatted_running_time},
                {
                    "label": "Avg Sensor Glucose",
                    "value": (f"{kpis.avg_sensor_glucose:.0f} mg/dL" if kpis.avg_sensor_glucose is not None else "N/A"),
                },
                {
                    "label": "Time in Range",
                    "value": (
                        f"{kpis.time_in_range_percentage:.0f}%" if kpis.time_in_range_percentage is not None else "N/A"
                    ),
                },
            ],
            charts=charts,
            pending_questionnaires=dashboard_data.pending_questionnaires,
        )

    def _build_charts(
        self, *, data_processor: DataProcessor, dashboard_data: DashboardOverviewData
    ) -> dict[str, Markup]:
        run_type_order = [RunType.EASY, RunType.INTERVAL, RunType.TEMPO, RunType.LONG, RunType.RACE]
        return {
            "activity_calendar": render_plotly_figure(figure=create_activity_calendar_chart(dashboard_data.summary)),
            "run_type_pie": render_plotly_figure(
                figure=create_run_type_pie_chart(data_processor=data_processor, run_type_order=run_type_order),
            ),
            "run_type_distance": render_plotly_figure(
                figure=create_run_type_distance_chart(data_processor=data_processor, run_type_order=run_type_order),
            ),
            "run_type_heartrate": render_plotly_figure(
                figure=create_run_type_heartrate_chart(data_processor=data_processor, run_type_order=run_type_order),
            ),
            "run_type_glucose": render_plotly_figure(
                figure=create_run_type_glucose_chart(data_processor=data_processor, run_type_order=run_type_order),
            ),
            "in_out_sg": render_plotly_figure(
                figure=create_in_going_out_going_sensor_glucose_chart(data_processor=data_processor),
            ),
            "iob_norm_change": render_plotly_figure(
                figure=create_insulin_on_board_and_normalized_glucose_change_chart(data_processor),
            ),
            "pre_nutrition_impact": render_plotly_figure(figure=create_pre_nutrition_impact_chart(data_processor)),
            "pre_nutrition_bolus": render_plotly_figure(figure=create_pre_nutrition_bolus_chart(data_processor)),
            "pre_nutrition_timing": render_plotly_figure(figure=create_pre_nutrition_timing_chart(data_processor)),
            "pre_nutrition_heatmap": render_plotly_figure(figure=create_pre_nutrition_heatmap(data_processor)),
            "fueling_response": render_plotly_figure(
                figure=create_fueling_glucose_response_chart(data_processor=data_processor),
            ),
            "fueling_carbs_peak": render_plotly_figure(
                figure=create_fueling_carbs_vs_peak_chart(data_processor=data_processor),
            ),
            "basal_adjustment_tir": render_plotly_figure(
                figure=create_basal_adjustment_tir_chart(data_processor=data_processor),
            ),
            "time_of_day_outcomes": render_plotly_figure(
                figure=create_time_of_day_outcomes_chart(data_processor=data_processor),
            ),
            "time_of_day_pre_run_profile": render_plotly_figure(
                figure=create_time_of_day_pre_run_profile_chart(data_processor=data_processor),
            ),
            "first20_stability_effect": render_plotly_figure(
                figure=create_first20_stability_effect_chart(data_processor=data_processor),
            ),
            "basal_lead_time_effect": render_plotly_figure(
                figure=create_basal_lead_time_effect_chart(data_processor=data_processor),
            ),
            "sg20_predictor": render_plotly_figure(
                figure=create_sg20_predictor_chart(data_processor=data_processor),
            ),
            "similar_runs_benchmark": render_plotly_figure(
                figure=create_similar_runs_benchmark_chart(data_processor=data_processor),
            ),
        }


_OVERVIEW_PAGE_SERVICES: dict[tuple[str, ...], OverviewPageService] = {}
_OVERVIEW_PAGE_SERVICES_LOCK = Lock()


def get_overview_page_service(*, data_paths: DataPaths) -> OverviewPageService:
    service_key = get_data_paths_key(data_paths=data_paths)
    with _OVERVIEW_PAGE_SERVICES_LOCK:
        if service_key not in _OVERVIEW_PAGE_SERVICES:
            _OVERVIEW_PAGE_SERVICES[service_key] = OverviewPageService(
                data_paths=data_paths,
                overview_data_service=get_overview_data_service(data_paths=data_paths),
            )
        return _OVERVIEW_PAGE_SERVICES[service_key]


def invalidate_overview_page_service(*, data_paths: DataPaths) -> None:
    service_key = get_data_paths_key(data_paths=data_paths)
    with _OVERVIEW_PAGE_SERVICES_LOCK:
        service = _OVERVIEW_PAGE_SERVICES.get(service_key)

    if service is not None:
        service.invalidate()
