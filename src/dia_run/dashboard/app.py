import polars as pl
import streamlit as st

from dia_run.dashboard.charts.run_types import (
    create_run_type_distance_chart,
    create_run_type_glucose_chart,
    create_run_type_heartrate_chart,
    create_run_type_pie_chart,
)
from dia_run.dashboard.charts.single_activity import create_single_activity_carelink_chart
from dia_run.data_models.paths import DataPaths
from dia_run.data_models.run_types import RunType
from dia_run.data_processing.data_processing import DataProcessor

data_paths = DataPaths()

data_processor = DataProcessor(data_paths)
df_summary = data_processor.get_summary()

st.set_page_config(
    page_title="Dia-Run",
    page_icon=":running:",
)

st.title("Dia-Run Dashboard")
tab1, tab2 = st.tabs(["General", "Run Type Analysis"])

with tab1:
    st.header("Overview of Running Activities :runner:")
    st.write(
        df_summary.select(
            "name",
            "distance_in_km",
            "human_readable_time",
            "human_readable_pace",
            "average_heartrate",
            "kilojoules",
            "insulin_on_board_in_going",
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
        st.subheader("Diabetes Management :syringe:")
        activity_id = df_summary.filter(pl.col("name_date") == name_date).select("activity_id")["activity_id"][0]
        st.plotly_chart(
            create_single_activity_carelink_chart(data_processor=data_processor, activity_id=activity_id),
            use_container_width=True,
        )

        questionnaire = data_processor.get_questionnaire(activity_id)
        left_column, right_column = st.columns(2)
        with left_column:
            st.subheader("Pre-Run Nutrition :pizza:", divider="orange")
            if questionnaire["pre_run"]:
                st.markdown(
                    f"""
                    - **Amount of carbohydrates:** :orange[{questionnaire["pre_run"]["carbohydrates_g"]}g]
                    - **Type of food:** :orange[{questionnaire["pre_run"]["food_type"]}]
                    - **Bolusing percentage:** :orange[{questionnaire["pre_run"]["bolus_percentage"]}%]
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
                        - **Amount of carbohydrates:** :blue[{fuel["carbohydrates_g"]}g]
                        - **Type of food:** :blue[{fuel["food_type"]}]
                        """
                    )
            else:
                st.markdown("No fueling during run")

with tab2:
    run_type_order = [RunType.EASY, RunType.INTERVAL, RunType.TEMPO, RunType.LONG]
    left_column, right_column = st.columns(2)
    with left_column:
        st.plotly_chart(create_run_type_pie_chart(data_processor), use_container_width=True)

    with right_column:
        st.plotly_chart(
            create_run_type_distance_chart(data_processor=data_processor, run_type_order=run_type_order),
            use_container_width=True,
        )

    st.plotly_chart(
        create_run_type_heartrate_chart(data_processor=data_processor, run_type_order=run_type_order),
        use_container_width=True,
    )

    st.plotly_chart(
        create_run_type_glucose_chart(data_processor=data_processor, run_type_order=run_type_order),
        use_container_width=True,
    )
