import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import polars as pl

from dia_run.dashboard.charts.theme import (
    ASH_GREY,
    COLOR_MUTED,
    MAIN_COLOR,
    MAIN_COLOR_SHADE_300,
    MAIN_COLOR_SHADE_500,
    NAVY,
    TARGET_RANGE_FILL,
    get_default_layout,
    get_empty_chart_layout,
)
from dia_run.data_models.constants import TARGET_GLUCOSE_LOWER, TARGET_GLUCOSE_UPPER
from dia_run.data_processing.data_processing import DataProcessor


def create_in_going_out_going_sensor_glucose_chart(data_processor: DataProcessor) -> px.scatter:
    df_summary = data_processor.get_summary()
    df_summary = df_summary.drop_nulls(subset=["in_going_sg", "out_going_sg"]).with_columns(
        pl.concat_list("insulin_on_board_in_going", "insulin_on_board_in_going", None).alias("line_x"),
        pl.concat_list("in_going_sg", "out_going_sg", None).alias("line_y"),
    )

    fig = go.Figure(
        data=[
            go.Scatter(
                x=df_summary.explode("line_x")["line_x"],
                y=df_summary.explode("line_y")["line_y"],
                mode="lines",
                showlegend=False,
                line=dict(color=MAIN_COLOR_SHADE_300, width=1.5),
            ),
            go.Scatter(
                x=df_summary["insulin_on_board_in_going"],
                y=df_summary["in_going_sg"],
                mode="markers",
                name="Start",
                marker=dict(color=MAIN_COLOR_SHADE_300, size=11, line={"width": 1, "color": NAVY}),
                hovertext=df_summary["name_date"],
                hoverinfo="text",
            ),
            go.Scatter(
                x=df_summary["insulin_on_board_in_going"],
                y=df_summary["out_going_sg"],
                mode="markers",
                name="End",
                marker=dict(color=MAIN_COLOR, size=11, line={"width": 1, "color": MAIN_COLOR_SHADE_300}),
                hovertext=df_summary["name_date"],
                hoverinfo="text",
            ),
        ]
    )
    fig.add_shape(
        type="rect",
        xref="x",
        yref="y",
        x0=df_summary["insulin_on_board_in_going"].min() - 0.1,
        y0=TARGET_GLUCOSE_LOWER,
        x1=df_summary["insulin_on_board_in_going"].max() + 0.1,
        y1=TARGET_GLUCOSE_UPPER,
        fillcolor=TARGET_RANGE_FILL,
        opacity=0.3,
        layer="below",
        line_width=0,
    )
    fig.update_layout(
        **get_default_layout(
            title="Insulin on Board at Start vs. Change in Sensor Glucose",
            xaxis_title="Insulin on Board at Start [U]",
            yaxis_title="Sensor Glucose During Activity [mg/dl]",
        )
    )

    return fig


def create_insulin_on_board_and_normalized_glucose_change_chart(data_processor: DataProcessor) -> px.scatter:
    df_summary = data_processor.get_summary()
    df_summary = df_summary.with_columns(
        (
            (pl.col("out_going_sg") - pl.col("in_going_sg"))
            / ((pl.col("end_date_local") - pl.col("start_date_local")).dt.total_seconds() / 60)
        ).alias("normalized_glucose_change")
    )
    fig = px.scatter(
        data_frame=df_summary,
        x="insulin_on_board_in_going",
        y="normalized_glucose_change",
        trendline="ols",
        custom_data={"name_date"},
    )
    fig.update_traces(
        hovertemplate="<b>%{customdata[0]}</b><extra></extra>",
        marker={"color": MAIN_COLOR_SHADE_500, "size": 10, "line": {"width": 1, "color": NAVY}},
        selector={"mode": "markers"},
    )
    fig.update_traces(line={"color": MAIN_COLOR, "width": 3}, selector={"mode": "lines"})
    fig.update_layout(
        **get_default_layout(
            title="Insulin on Board at Start vs. Normalized Change in Sensor Glucose",
            xaxis_title="Insulin on Board at Start [U]",
            yaxis_title="Normalized Sensor Glucose Change <br>During Activity [mg/dl/min]",
        )
    )
    return fig


def create_pre_nutrition_impact_chart(data_processor: DataProcessor) -> go.Figure:
    df_nutrition = data_processor.get_pre_run_nutrition_summary()

    if df_nutrition.is_empty():
        fig = go.Figure()
        fig.update_layout(
            **get_empty_chart_layout(
                title="Pre-Run Nutrition Impact on In-Going Sensor Glucose",
                message="No pre-run nutrition data available",
            )
        )
        return fig

    minutes_before_start = df_nutrition["earliest_time_before_start_min"].abs().to_numpy()

    fig = go.Figure(
        data=[
            go.Scatter(
                x=df_nutrition["total_carbohydrates_g"],
                y=df_nutrition["in_going_sg"],
                mode="markers",
                marker=dict(
                    size=10,
                    color=df_nutrition["avg_bolus_percentage"],
                    colorscale=[(0, MAIN_COLOR_SHADE_300), (0.5, MAIN_COLOR_SHADE_500), (1, MAIN_COLOR)],
                    colorbar=dict(title="Bolus [%]", tickfont={"color": COLOR_MUTED}),
                    showscale=True,
                    line=dict(width=1, color=NAVY),
                ),
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "Carbs: %{x}g<br>"
                    "In-Going SG: %{y:.0f} mg/dL<br>"
                    "Timing: %{customdata[1]} min before<br>"
                    "Bolus: %{customdata[2]:.0f}%"
                    "<extra></extra>"
                ),
                customdata=np.column_stack(
                    [
                        df_nutrition["name_date"].to_numpy(),
                        minutes_before_start,
                        df_nutrition["avg_bolus_percentage"].to_numpy(),
                    ]
                ),
            )
        ]
    )

    x_min = df_nutrition["total_carbohydrates_g"].min() - 5
    x_max = df_nutrition["total_carbohydrates_g"].max() + 5
    fig.add_shape(
        type="rect",
        xref="x",
        yref="y",
        x0=x_min,
        y0=TARGET_GLUCOSE_LOWER,
        x1=x_max,
        y1=TARGET_GLUCOSE_UPPER,
        fillcolor=TARGET_RANGE_FILL,
        opacity=0.3,
        layer="below",
        line_width=0,
    )

    fig.update_layout(
        **get_default_layout(
            title="Pre-Run Nutrition Impact on In-Going Sensor Glucose",
            xaxis_title="Total Pre-Run Carbohydrates [g]",
            yaxis_title="In-Going Sensor Glucose [mg/dL]",
        )
    )

    return fig


def create_pre_nutrition_bolus_chart(data_processor: DataProcessor) -> go.Figure:
    df_nutrition = data_processor.get_pre_run_nutrition_summary()

    if df_nutrition.is_empty():
        fig = go.Figure()
        fig.update_layout(
            **get_empty_chart_layout(
                title="Pre-Run Bolus Percentage vs. In-Going Sensor Glucose",
                message="No pre-run nutrition data available",
            )
        )
        return fig

    minutes_before_start = df_nutrition["earliest_time_before_start_min"].abs().to_numpy()
    carbs = df_nutrition["total_carbohydrates_g"].to_numpy().astype(float)
    bolus_percentages = df_nutrition["avg_bolus_percentage"].to_numpy().astype(float)
    jitter = np.random.default_rng(0).uniform(-1.0, 1.0, size=bolus_percentages.shape)
    bolus_percentages = np.clip(bolus_percentages + jitter, 0.0, 100.0)

    fig = go.Figure(
        data=[
            go.Scatter(
                x=bolus_percentages,
                y=df_nutrition["in_going_sg"],
                mode="markers",
                marker=dict(
                    size=10,
                    color=MAIN_COLOR_SHADE_500,
                    opacity=0.6,
                    line=dict(width=1, color=NAVY),
                ),
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "Bolus: %{x:.0f}%<br>"
                    "In-Going SG: %{y:.0f} mg/dL<br>"
                    "Carbs: %{customdata[1]}g<br>"
                    "Timing: %{customdata[2]} min before"
                    "<extra></extra>"
                ),
                customdata=np.column_stack(
                    [
                        df_nutrition["name_date"].to_numpy(),
                        carbs,
                        minutes_before_start,
                    ]
                ),
            )
        ]
    )

    x_min = float(bolus_percentages.min()) - 5
    x_max = float(bolus_percentages.max()) + 5
    fig.add_shape(
        type="rect",
        xref="x",
        yref="y",
        x0=x_min,
        y0=TARGET_GLUCOSE_LOWER,
        x1=x_max,
        y1=TARGET_GLUCOSE_UPPER,
        fillcolor=TARGET_RANGE_FILL,
        opacity=0.3,
        layer="below",
        line_width=0,
    )

    fig.update_layout(
        **get_default_layout(
            title="Pre-Run Bolus Percentage vs. In-Going Sensor Glucose",
            xaxis_title="Bolus Percentage [%]",
            yaxis_title="In-Going Sensor Glucose [mg/dL]",
        )
    )

    return fig


def create_pre_nutrition_timing_chart(data_processor: DataProcessor) -> go.Figure:
    df_nutrition = data_processor.get_pre_run_nutrition_summary()

    if df_nutrition.is_empty():
        fig = go.Figure()
        fig.update_layout(
            **get_empty_chart_layout(
                title="Pre-Run Nutrition Timing vs. In-Going Sensor Glucose",
                message="No pre-run nutrition data available",
            )
        )
        return fig

    minutes_before_start = df_nutrition["earliest_time_before_start_min"].abs().to_numpy()
    carbs = df_nutrition["total_carbohydrates_g"].to_numpy().astype(float)

    fig = go.Figure(
        data=[
            go.Scatter(
                x=minutes_before_start,
                y=df_nutrition["in_going_sg"],
                mode="markers",
                marker=dict(
                    size=10,
                    color=MAIN_COLOR_SHADE_500,
                    line=dict(width=1, color=NAVY),
                ),
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "Timing: %{x} min before<br>"
                    "In-Going SG: %{y:.0f} mg/dL<br>"
                    "Carbs: %{customdata[1]}g"
                    "<extra></extra>"
                ),
                customdata=np.column_stack(
                    [
                        df_nutrition["name_date"].to_numpy(),
                        carbs,
                    ]
                ),
            )
        ]
    )

    x_min = float(minutes_before_start.min()) - 5
    x_max = float(minutes_before_start.max()) + 5
    fig.add_shape(
        type="rect",
        xref="x",
        yref="y",
        x0=x_min,
        y0=TARGET_GLUCOSE_LOWER,
        x1=x_max,
        y1=TARGET_GLUCOSE_UPPER,
        fillcolor=TARGET_RANGE_FILL,
        opacity=0.3,
        layer="below",
        line_width=0,
    )

    fig.update_layout(
        **get_default_layout(
            title="Pre-Run Nutrition Timing vs. In-Going Sensor Glucose",
            xaxis_title="Minutes Before Start",
            yaxis_title="In-Going Sensor Glucose [mg/dL]",
        )
    )

    return fig


def create_pre_nutrition_heatmap(data_processor: DataProcessor) -> go.Figure:
    df_nutrition = data_processor.get_pre_run_nutrition_summary()

    if df_nutrition.is_empty():
        fig = go.Figure()
        fig.update_layout(
            **get_empty_chart_layout(
                title="Pre-Run Nutrition Heatmap: Carbs x Timing -> Avg In-Going Sensor Glucose",
                message="No pre-run nutrition data available",
            )
        )
        return fig

    carb_bin_size = 10
    time_bin_size = 15

    df_binned = df_nutrition.with_columns(
        (pl.col("total_carbohydrates_g") // carb_bin_size * carb_bin_size).alias("carb_bin"),
        (pl.col("earliest_time_before_start_min").abs() // time_bin_size * time_bin_size).alias("time_bin"),
    )

    df_agg = (
        df_binned.group_by("carb_bin", "time_bin")
        .agg(
            pl.col("in_going_sg").mean().alias("avg_in_going_sg"),
            pl.col("in_going_sg").count().alias("count"),
        )
        .sort("time_bin", "carb_bin")
    )

    carb_bins = sorted(df_agg["carb_bin"].unique().to_list())
    time_bins = sorted(df_agg["time_bin"].unique().to_list())

    z_values: list[list[float | None]] = []
    hover_text: list[list[str]] = []
    for time_bin in time_bins:
        z_row: list[float | None] = []
        hover_row: list[str] = []
        for carb_bin in carb_bins:
            match = df_agg.filter((pl.col("carb_bin") == carb_bin) & (pl.col("time_bin") == time_bin))
            if match.is_empty():
                z_row.append(None)
                hover_row.append("")
            else:
                avg_sg = round(match["avg_in_going_sg"].item(), 0)
                count = match["count"].item()
                z_row.append(avg_sg)
                hover_row.append(f"Avg SG: {avg_sg:.0f} mg/dL<br>n={count}")
        z_values.append(z_row)
        hover_text.append(hover_row)

    carb_labels = [f"{b}-{b + carb_bin_size}g" for b in carb_bins]
    time_labels = [f"{b}-{b + time_bin_size} min" for b in time_bins]

    flat_values = [v for row in z_values for v in row if v is not None]
    z_min = min(flat_values)
    z_max = max(flat_values)

    if z_max == z_min:
        colorscale: list[list[float | str]] = [
            [0.0, MAIN_COLOR],
            [1.0, MAIN_COLOR],
        ]
    else:
        low_target_pos = float((TARGET_GLUCOSE_LOWER - z_min) / (z_max - z_min))
        high_target_pos = float((TARGET_GLUCOSE_UPPER - z_min) / (z_max - z_min))

        low_target_pos = min(1.0, max(0.0, low_target_pos))
        high_target_pos = min(1.0, max(0.0, high_target_pos))
        low_target_pos, high_target_pos = sorted((low_target_pos, high_target_pos))

        if low_target_pos == high_target_pos:
            high_target_pos = min(1.0, low_target_pos + 0.01)

        target_mid_pos = (low_target_pos + high_target_pos) / 2

        colorscale = [
            [0.0, ASH_GREY],
            [low_target_pos, MAIN_COLOR_SHADE_500],
            [target_mid_pos, MAIN_COLOR],
            [high_target_pos, MAIN_COLOR_SHADE_500],
            [1.0, ASH_GREY],
        ]

    fig = go.Figure(
        data=go.Heatmap(
            z=z_values,
            x=carb_labels,
            y=time_labels,
            colorscale=colorscale,
            zmin=z_min,
            zmax=z_max,
            colorbar=dict(title="Avg In-Going<br>SG [mg/dL]", tickfont={"color": COLOR_MUTED}),
            hovertext=hover_text,
            hovertemplate="Carbs: %{x}<br>Timing: %{y}<br>%{hovertext}<extra></extra>",
        )
    )

    fig.update_layout(
        **get_default_layout(
            title="Pre-Run Nutrition Heatmap: Carbs x Timing -> Avg In-Going Sensor Glucose",
            xaxis_title="Total Pre-Run Carbohydrates",
            yaxis_title="Minutes Before Start",
        )
    )

    return fig
