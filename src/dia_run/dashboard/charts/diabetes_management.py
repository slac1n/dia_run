import plotly.express as px
import plotly.graph_objects as go
import polars as pl

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
                marker=dict(color="grey"),
            ),
            go.Scatter(
                x=df_summary["insulin_on_board_in_going"],
                y=df_summary["in_going_sg"],
                mode="markers",
                name="Start",
                marker=dict(color="green", size=10),
                hovertext=df_summary["name_date"],
                hoverinfo="text",
            ),
            go.Scatter(
                x=df_summary["insulin_on_board_in_going"],
                y=df_summary["out_going_sg"],
                mode="markers",
                name="End",
                marker=dict(color="red", size=10),
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
        y0=180,
        x1=df_summary["insulin_on_board_in_going"].max() + 0.1,
        y1=220,
        fillcolor="LightGray",
        opacity=0.2,
        layer="below",
        line_width=0,
    )
    fig.update_layout(
        title="Insulin on Board at Start vs. Change in Sensor Glucose",
        xaxis_title="Insulin on Board at Start [U]",
        yaxis_title="Sensor Glucose During Activity [mg/dl]",
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
    fig.update_traces(hovertemplate="<b>%{customdata[0]}</b>")
    fig.update_layout(
        title="Insulin on Board at Start vs. Normalized Change in Sensor Glucose",
        xaxis_title="Insulin on Board at Start [U]",
        yaxis_title="Normalized Sensor Glucose Change <br>During Activity [mg/dl/min]",
    )
    return fig
