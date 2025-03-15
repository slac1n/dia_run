import json
from datetime import timedelta

import plotly.graph_objects as go
import polars as pl
import streamlit as st
from plotly.subplots import make_subplots

from dia_run.data_models.paths import DataPaths

data_paths = DataPaths()


# Load the Delta table using pl.scan_delta
df_summary = pl.scan_delta(str(data_paths.strava_summary)).with_columns(
    pl.format(
        "{}:{}",
        (pl.col("elapsed_time") // 3600),  # Hours
        (pl.col("elapsed_time") % 3600) // 60,  # Minutes
    ).alias("human_readable_time"),
    pl.format(
        "{}:{}",
        (pl.col("average_pace").floor().cast(int)),  # Minutes
        ((pl.col("average_pace") % 1) * 60).round(0).cast(int),  # Fractional minutes to seconds
    ).alias("human_readable_pace"),
    pl.format(
        "{}",
        (pl.col("distance") / 1000).round(1),  # Convert meters to kilometers
    ).alias("distance_in_km"),
    (pl.col("start_date_local") + pl.duration(seconds=pl.col("elapsed_time"))).alias("end_date_local"),
    pl.format(
        "{} on {}",
        pl.col("name"),  # and only the date
        pl.col("start_date_local").dt.date(),
    ).alias("name_date"),
)

df_carelink = (
    pl.scan_delta(str(data_paths.carelink))
    .filter(pl.col("type") == "CGM")
    .join(
        df_summary.select("activity_id", "start_date_local", "end_date_local"),
        on="activity_id",
        how="inner",
    )
    .filter(
        (pl.col("datetime") >= pl.col("start_date_local") - pl.duration(minutes=5))
        & (pl.col("datetime") <= pl.col("end_date_local") + pl.duration(minutes=5))
    )
    .group_by("activity_id")
    .agg(
        [
            pl.col("value").first().alias("in_going_sg"),
            pl.col("value").last().alias("out_going_sg"),
            pl.col("value").mean().alias("avg_sg"),
        ]
    )
)

df_summary = df_summary.join(
    df_carelink,
    on="activity_id",
    how="left",
)

# Collect the dataframes
df_carelink = df_carelink.collect()
df_summary = df_summary.collect()
st.title("Dia-Run Dashboard")
st.header("Overview of Running Activities :runner:")
st.write(
    df_summary.select(
        "name",
        "distance_in_km",
        "human_readable_time",
        "human_readable_pace",
        "average_heartrate",
        "kilojoules",
        "in_going_sg",
        "out_going_sg",
        "avg_sg",
    )
)
st.header("Activity Details :mag:")
name_date = st.selectbox(
    "Select an activity",
    df_summary.select("name_date"),
    index=None,
    placeholder="Select an activity",
)

if name_date is not None:
    # Get the activity_id by filtering the name_date
    sel_activity_id = df_summary.filter(pl.col("name_date") == name_date).select(
        "activity_id"
    )["activity_id"][0]
    sel_start_date_local = df_summary.filter(pl.col("name_date") == name_date).select(
        "start_date_local"
    )["start_date_local"][0]
    sel_end_date_local = df_summary.filter(pl.col("name_date") == name_date).select(
        "end_date_local"
    )["end_date_local"][0]

    sel_df_carelink = (
        pl.scan_delta(str(CARELINK_DIR))
        .filter(
            (pl.col("datetime") >= sel_start_date_local - pl.duration(hours=2))
            & (pl.col("datetime") <= sel_end_date_local + pl.duration(minutes=5))
            & (pl.col("activity_id") == sel_activity_id)
        )
        .collect()
    )
    sel_df_carelink_cgm = sel_df_carelink.filter(pl.col("type") == "CGM")
    sel_df_carelink_basal = sel_df_carelink.filter(
        pl.col("type") == "AUTO_BASAL_DELIVERY"
    )
    sel_df_carelink_bolus = sel_df_carelink.filter(pl.col("type") == "INSULIN")

    sel_df_strava_stream = (
        pl.scan_delta(str(STRAVE_STREAM_DIR))
        .filter((pl.col("activity_id") == sel_activity_id) & (pl.col("moving") == True))
        .with_columns(
            pl.col("pace").rolling_mean(20).alias("pace_smooth"),
        )
        .collect()
    )

    # load json file from questionnaire
    with open(QUESTIONNAIRE_DIR / f"{sel_activity_id}.json") as f:
        questionnaire = json.load(f)

    st.subheader("Diabetes Management :syringe:")
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Scatter(
            x=sel_df_carelink_cgm["datetime"],
            y=sel_df_carelink_cgm["value"],
            name="Sensor Glucose",
            mode="lines",
        ),
        secondary_y=False,
    )
    # ylim between 70 and 250
    fig.update_yaxes(
        range=[70, 250], secondary_y=False, title_text="Sensor Glucose [mg/dl]"
    )

    if not sel_df_carelink_basal.is_empty():
        fig.add_trace(
            go.Bar(
                x=sel_df_carelink_basal["datetime"],
                y=sel_df_carelink_basal["value"],
                name="Basal Insulin",
            ),
            secondary_y=True,
        )
        fig.update_yaxes(
            range=[0, 2],
            secondary_y=True,
            showgrid=False,
            showticklabels=False,
        )
    if not sel_df_carelink_bolus.is_empty():
        fig.add_trace(
            go.Bar(
                x=sel_df_carelink_bolus["datetime"],
                y=sel_df_carelink_bolus["value"],
                name="Bolus Insulin",
            ),
            secondary_y=True,
        )

    # add a vertical line for the start of the activity
    fig.add_vline(
        x=sel_start_date_local, line_width=1, line_dash="dash", line_color="green"
    )
    # add a vertical line for the end of the activity
    fig.add_vline(
        x=sel_end_date_local, line_width=1, line_dash="dash", line_color="red"
    )

    # make the the background between 180 and 220 light gray indicating the target range
    fig.add_shape(
        type="rect",
        xref="x",
        yref="y",
        x0=sel_start_date_local,
        y0=180,
        x1=sel_end_date_local,
        y1=220,
        fillcolor="LightGray",
        opacity=0.2,
        layer="below",
        line_width=0,
    )

    # check if 'pre_run' in questionnaire is not empty
    if questionnaire["pre_run"]:
        prerun_time = int(questionnaire["pre_run"]["time_before_start_min"])

        if prerun_time < 0:
            # make time absolute
            prerun_time = abs(prerun_time)
            prerun_time = sel_start_date_local - timedelta(minutes=prerun_time)
        fig.add_vline(
            x=prerun_time, line_width=1, line_dash="dash", line_color="orange"
        )

    # check if 'fuel_during_run' in questionnaire is not empty
    if questionnaire["fueling_during_run"]:
        for fuel in questionnaire["fueling_during_run"]:
            fuel_time = int(fuel["time_during_run_min"])
            fuel_time = sel_start_date_local + timedelta(minutes=fuel_time)
            fig.add_vline(
                x=fuel_time,
                line_width=1,
                line_dash="dash",
                line_color="blue",
            )

    st.plotly_chart(fig, use_container_width=True)

    left_column, right_column = st.columns(2)
    with left_column:
        st.subheader("Pre-Run Nutrition :pizza:", divider="orange")
        if questionnaire["pre_run"]:
            st.markdown(
                f"""
                - **Amount of carbohydrates:** :orange[{questionnaire['pre_run']['carbohydrates_g']}g]
                - **Type of food:** :orange[{questionnaire['pre_run']['food_type']}]
                - **Bolusing percentage:** :orange[{questionnaire['pre_run']['bolus_percentage']}%]
                """
            )
        else:
            st.markdown("No pre-run nutrition")

    with right_column:
        st.subheader("Fueling During Run :banana:", divider="blue")
        if questionnaire["fueling_during_run"]:
            for counter, fuel in enumerate(questionnaire["fueling_during_run"]):
                st.markdown(
                    f"""
                    ##### Fueling Instance: {counter + 1}
                    - **Amount of carbohydrates:** :blue[{fuel['carbohydrates_g']}g]
                    - **Type of food:** :blue[{fuel['food_type']}]
                    """
                )
        else:
            st.markdown("No fueling during run")

    st.subheader("Run :running:", divider="green")

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Scatter(
            x=sel_df_carelink_cgm.filter(
                pl.col("datetime") >= sel_start_date_local - pl.duration(minutes=5)
            )["datetime"],
            y=sel_df_carelink_cgm.filter(
                pl.col("datetime") >= sel_start_date_local - pl.duration(minutes=5)
            )["value"],
            name="Sensor Glucose",
            mode="lines",
        ),
        secondary_y=False,
    )
    # ylim between 70 and 250
    fig.update_yaxes(
        range=[70, 250], secondary_y=False, title_text="Sensor Glucose [mg/dl]"
    )
    fig.add_trace(
        go.Scatter(
            x=sel_df_strava_stream["datetime"],
            y=sel_df_strava_stream["heartrate"],
            name="Heart Rate",
            mode="lines",
            line={"color": "red"},
        ),
        secondary_y=True,
    )
    fig.add_hrect(
        y0=180,
        y1=220,
        line_width=0,
        fillcolor="LightGray",
        opacity=0.2,
        layer="below",
    )
    fig.add_trace(
        go.Scatter(
            x=sel_df_strava_stream["datetime"],
            y=sel_df_strava_stream["pace_smooth"],
            name="Pace",
            mode="lines",
            line={"color": "green"},
            visible="legendonly",
        ),
        secondary_y=True,
    )
    st.plotly_chart(fig, use_container_width=True)
