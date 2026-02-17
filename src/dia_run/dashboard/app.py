import polars as pl
import streamlit as st

from dia_run.dashboard.charts.activity_calendar import create_activity_calendar_chart
from dia_run.dashboard.charts.diabetes_management import (
    create_in_going_out_going_sensor_glucose_chart,
    create_insulin_on_board_and_normalized_glucose_change_chart,
    create_pre_nutrition_heatmap,
    create_pre_nutrition_impact_chart,
    create_pre_nutrition_timing_chart,
)
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
kpis = data_processor.get_30_day_kpis()

st.set_page_config(
    page_title="Dia-Run",
    page_icon=":running:",
)

st.title("Dia-Run Dashboard")

st.subheader("Last 30 Days")
kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
kpi_col1.metric("Total Distance", f"{kpis.total_distance_km:.1f} km")
kpi_col2.metric("Total Running Time", kpis.formatted_running_time)
kpi_col3.metric("Avg Sensor Glucose", f"{kpis.avg_sensor_glucose:.0f} mg/dL" if kpis.avg_sensor_glucose else "N/A")
kpi_col4.metric(
    "Time in Range", f"{kpis.time_in_range_percentage:.0f}%" if kpis.time_in_range_percentage is not None else "N/A"
)

tab1, tab2, tab3 = st.tabs(["Activities", "Run Type Analysis", "Diabetes Insights"])

with tab1:
    st.header("Overview of Running Activities :runner:")
    st.plotly_chart(create_activity_calendar_chart(df_summary), use_container_width=True)
    rename_dict = {
        "name": "Activity Name",
        "date": "Date",
        "distance_in_km": "Distance",
        "human_readable_time": "Time",
        "human_readable_pace": "Pace",
        "average_heartrate": "Avg. Heartrate",
        "insulin_on_board_in_going": "Insulin on Board",
        "avg_sg": "Avg. SG",
        "in_going_sg": "In Going SG",
        "out_going_sg": "Out Going SG",
    }
    st.write(df_summary.select(rename_dict.keys()).rename(rename_dict))
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
            if questionnaire.pre_run:
                for pre_run in questionnaire.pre_run:
                    st.markdown(
                        f"""
                        - **Amount of carbohydrates:** :orange[{pre_run.carbohydrates_g}g]
                        - **Type of food:** :orange[{pre_run.food_type}]
                        - **Bolusing percentage:** :orange[{pre_run.bolus_percentage}%]
                        """
                    )
            else:
                st.markdown("No pre-run nutrition")

        with right_column:
            st.subheader("Fueling During Run :banana:", divider="blue")
            if questionnaire.fueling_during_run:
                for counter, fuel in enumerate(questionnaire.fueling_during_run):
                    st.markdown(
                        f"""
                        ##### Fueling Instance: {counter + 1}
                        - **Amount of carbohydrates:** :blue[{fuel.carbohydrates_g}g]
                        - **Type of food:** :blue[{fuel.food_type}]
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

with tab3:
    st.plotly_chart(
        create_in_going_out_going_sensor_glucose_chart(data_processor=data_processor),
        use_container_width=True,
    )
    st.plotly_chart(
        create_insulin_on_board_and_normalized_glucose_change_chart(data_processor=data_processor),
        use_container_width=True,
    )
    st.plotly_chart(
        create_pre_nutrition_impact_chart(data_processor=data_processor),
        use_container_width=True,
    )
    st.plotly_chart(
        create_pre_nutrition_timing_chart(data_processor=data_processor),
        use_container_width=True,
    )
    st.plotly_chart(
        create_pre_nutrition_heatmap(data_processor=data_processor),
        use_container_width=True,
    )
