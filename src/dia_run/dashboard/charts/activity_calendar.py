from datetime import datetime, timedelta

import plotly.graph_objects as go
import polars as pl

from dia_run.data_models.calendar import Calendar, CalendarWeek

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

ACTIVITY_COLOR_SCALE = [
    [0, "#161b22"],  # 0km (no activity)
    [0.001, "#0e4429"],  # >0 to 5km
    [0.25, "#006d32"],  # 5km to 10km
    [0.5, "#26a641"],  # 10km to 15km
    [0.75, "#2ea043"],  # 15km to 20km
    [1, "#39d353"],  # 20km+
]


def create_activity_calendar_chart(df: pl.DataFrame) -> go.Figure:
    current_year = datetime.now().year
    start_date = datetime(current_year, 1, 1)
    end_date = datetime(current_year, 12, 31)
    interval = timedelta(days=1)

    date_to_distance = _calculate_daily_distances(data=df, start_date=start_date)

    date_range = pl.date_range(start=start_date, end=end_date, interval=interval, eager=True)

    calendar = _create_distance_date_calendar(date_range=date_range, date_to_distance=date_to_distance)

    fig = _create_heatmap_figure(calendar=calendar)

    month_positions = _calculate_month_positions(start_date=start_date)

    _update_figure_layout(fig=fig, current_year=current_year, month_positions=month_positions)

    return fig


def _calculate_daily_distances(*, data: pl.DataFrame, start_date: datetime) -> dict[datetime.date, float]:
    daily_distances = (
        data.filter(pl.col("start_date_local") >= start_date)
        .with_columns([pl.col("distance_in_km").cast(pl.Float64).alias("distance_km_numeric")])
        .group_by("start_date_local")
        .agg(pl.sum("distance_km_numeric").alias("total_distance_km"))
    )

    return {row["start_date_local"].date(): row["total_distance_km"] for row in daily_distances.to_dicts()}


def _create_distance_date_calendar(*, date_range: pl.Series, date_to_distance: dict[datetime.date, float]) -> Calendar:
    calendar = Calendar(distance=[[] for _ in range(7)], dates=[[] for _ in range(7)])
    current_week = _reset_week()

    for i, date in enumerate(date_range):
        weekday = date.weekday()
        current_week.distance[weekday] = date_to_distance.get(date, 0.0)
        current_week.dates[weekday] = date.strftime("%Y-%m-%d")

        if weekday == 6 or i == len(date_range) - 1:
            calendar = _append_current_week_to_calendar(calendar=calendar, current_week=current_week)
            current_week = _reset_week()

    return calendar


def _reset_week() -> CalendarWeek:
    return CalendarWeek(distance=[None] * 7, dates=[None] * 7)


def _append_current_week_to_calendar(*, calendar: Calendar, current_week: CalendarWeek) -> Calendar:
    for day in range(7):
        calendar.distance[day].append(current_week.distance[day])
        calendar.dates[day].append(current_week.dates[day])
    return calendar


def _create_heatmap_figure(calendar: Calendar) -> go.Figure:
    return go.Figure(
        data=go.Heatmap(
            z=calendar.distance[::-1],
            y=WEEKDAYS[::-1],
            colorscale=ACTIVITY_COLOR_SCALE,
            zmin=0,
            zmax=20,
            showscale=False,
            hoverongaps=False,
            xgap=4,
            ygap=4,
            customdata=calendar.dates[::-1],
            hovertemplate="%{z}km on %{customdata}<extra></extra>",
        )
    )


def _calculate_month_positions(start_date: datetime) -> dict[str, int]:
    month_positions = {}
    for month in range(1, 13):
        first_day = datetime(start_date.year, month, 1)
        month_positions[MONTH_NAMES[month - 1]] = first_day.isocalendar()[1] - 1

    return month_positions


def _update_figure_layout(*, fig: go.Figure, current_year: int, month_positions: dict[str, int]) -> None:
    fig.update_layout(
        paper_bgcolor="#0d1117",
        plot_bgcolor="#0d1117",
        font=dict(
            color="#7d8590",
            size=12,
        ),
        title=dict(
            text=f"Running Distance Calendar {current_year}",
        ),
        height=180,
        margin=dict(l=50, r=10, t=40, b=20),
        xaxis=dict(
            showgrid=False,
            showline=False,
            zeroline=False,
            tickmode="array",
            tickvals=list(month_positions.values()),
            ticktext=list(month_positions.keys()),
        ),
        yaxis=dict(
            showgrid=False,
            showline=False,
            zeroline=False,
        ),
    )
