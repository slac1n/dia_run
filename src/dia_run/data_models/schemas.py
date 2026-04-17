import datetime

from pandera.polars import DataFrameModel, Field
from pandera.typing import Series

from dia_run.data_models.run_types import RunType


class StravaSummarySchema(DataFrameModel):
    activity_id: Series[int] = Field(unique=True)
    name: Series[str]
    start_date_local: Series[datetime.datetime]
    distance: Series[float] = Field(ge=0)
    moving_time: Series[int] = Field(ge=0)
    elapsed_time: Series[int] = Field(ge=0)
    total_elevation_gain: Series[float] = Field(ge=0)
    average_heartrate: Series[float] = Field(nullable=True, ge=0)
    max_heartrate: Series[int] = Field(nullable=True, ge=0)
    average_speed: Series[float] = Field(ge=0)
    max_speed: Series[float] = Field(ge=0)
    average_watts: Series[float] = Field(nullable=True, ge=0)
    max_watts: Series[int] = Field(nullable=True, ge=0)
    kilojoules: Series[float] = Field(nullable=True, ge=0)
    average_pace: Series[float] = Field(ge=0)
    max_pace: Series[float] = Field(ge=0)
    human_readable_time: Series[str]
    human_readable_pace: Series[str]
    distance_in_km: Series[str]
    end_date_local: Series[datetime.datetime]
    name_date: Series[str]
    date: Series[str]
    run_type: Series[str] = Field(isin=[rt.value for rt in RunType])


class SummarySchema(StravaSummarySchema):
    in_going_sg: Series[float] = Field(nullable=True, gt=0)
    out_going_sg: Series[float] = Field(nullable=True, gt=0)
    avg_sg: Series[float] = Field(nullable=True, gt=0)
    tir_pct: Series[float] = Field(nullable=True, ge=0, le=100)
    insulin_on_board_in_going: Series[float] = Field(nullable=True, ge=0)


class SpecificCarelinkSchema(DataFrameModel):
    datetime: Series[datetime.datetime]
    type: Series[str] = Field(
        isin=[
            "CGM",
            "AUTO_BASAL_DELIVERY",
            "INSULIN",
            "AUTO_MODE_STATUS",
            "MEAL",
            "LOW_GLUCOSE_SUSPENDED",
            "BG_READING",
            "CALIBRATION",
        ]
    )
    value: Series[float] = Field(nullable=True, gt=0)


class StreamsSchema(DataFrameModel):
    datetime: Series[datetime.datetime]
    run_type: Series[str] = Field(isin=[rt.value for rt in RunType])


class HeartrateStreamsSchema(StreamsSchema):
    heartrate: Series[int] = Field(nullable=True, gt=0)


class GlucoseStreamsSchema(StreamsSchema):
    value: Series[float] = Field(nullable=True, gt=0)


class BaseGlucoseStreamSchema(GlucoseStreamsSchema):
    activity_id: Series[int] = Field(unique=True)


class AggregatedGlucoseSchema(DataFrameModel):
    activity_id: Series[int] = Field(unique=True)
    avg_sg: Series[float] = Field(nullable=True, gt=0)
    in_going_sg: Series[float] = Field(nullable=True, gt=0)
    out_going_sg: Series[float] = Field(nullable=True, gt=0)
    tir_pct: Series[float] = Field(nullable=True, ge=0, le=100)


class AggregateInsulinOnBoard(DataFrameModel):
    activity_id: Series[int] = Field(unique=True)
    insulin_on_board_in_going: Series[float] = Field(ge=0)


class PreRunInsulinSchema(DataFrameModel):
    activity_id: Series[int] = Field(unique=True)
    datetime: Series[datetime.datetime]
    start_date_local: Series[datetime.datetime]
    value: Series[float] = Field(ge=0)


class PreRunNutritionSummarySchema(DataFrameModel):
    activity_id: Series[int] = Field(unique=True)
    total_carbohydrates_g: Series[int] = Field(gt=0)
    earliest_time_before_start_min: Series[int] = Field(le=0)
    avg_bolus_percentage: Series[float] = Field(ge=0)
    in_going_sg: Series[float] = Field(gt=0)
    name_date: Series[str]


class FuelingGlucoseWindowSchema(DataFrameModel):
    activity_id: Series[int]
    fueling_index: Series[int] = Field(ge=0)
    minutes_relative: Series[float]
    value: Series[float] = Field(nullable=True, gt=0)


class BasalAdjustmentTirSchema(DataFrameModel):
    activity_id: Series[int]
    adjustment_index: Series[int] = Field(ge=0)
    type: Series[str]
    basal_rate_percentage: Series[float] = Field(nullable=True, ge=0)
    duration_min: Series[int] = Field(gt=0)
    tir_pct: Series[float] = Field(ge=0, le=100)
    n_points: Series[int] = Field(ge=0)
    covered_minutes: Series[float] = Field(ge=0)
    name_date: Series[str]


class FuelingImpactSchema(DataFrameModel):
    activity_id: Series[int]
    fueling_index: Series[int] = Field(ge=0)
    carbohydrates_g: Series[int] = Field(gt=0)
    baseline_sg: Series[float] = Field(nullable=True, gt=0)
    peak_sg: Series[float] = Field(nullable=True, gt=0)
    peak_increase: Series[float] = Field(nullable=True)
    time_to_peak_min: Series[float] = Field(nullable=True)
    name_date: Series[str]


TIME_OF_DAY_BUCKETS = ["before_noon", "after_noon"]
DURATION_BANDS = ["<=45", "46-75", "76-120", ">120"]
GLUCOSE_BANDS = ["<100", "100-129", "130-159", "160-180", ">180"]
BASAL_LEAD_TIME_BUCKETS = ["none", "0-15", "16-30", "31-60", ">60"]
PATTERN_AGGREGATE_DIMS = ["time_of_day", "stability", "basal_lead_time", "sg20", "cohort"]


class PatternFeaturesSchema(DataFrameModel):
    activity_id: Series[int] = Field(unique=True)
    name_date: Series[str]
    start_date_local: Series[datetime.datetime]
    run_type: Series[str] = Field(isin=[rt.value for rt in RunType])
    tir_pct: Series[float] = Field(nullable=True, ge=0, le=100)
    out_going_sg: Series[float] = Field(nullable=True, gt=0)
    good_finish_flag: Series[bool] = Field(nullable=True)
    low_event_flag: Series[bool] = Field(nullable=True)
    run_variability_p90_p10: Series[float] = Field(nullable=True, ge=0)
    sg_start: Series[float] = Field(nullable=True, gt=0)
    sg_20: Series[float] = Field(nullable=True, gt=0)
    early_delta_20: Series[float] = Field(nullable=True)
    early_in_range_flag: Series[bool] = Field(nullable=True)
    stable_20_flag: Series[bool] = Field(nullable=True)
    early_span_20: Series[float] = Field(nullable=True, ge=0)
    time_of_day_bucket: Series[str] = Field(isin=TIME_OF_DAY_BUCKETS)
    duration_band: Series[str] = Field(isin=DURATION_BANDS)
    start_glucose_band: Series[str] = Field(nullable=True, isin=GLUCOSE_BANDS)
    sg_20_bin: Series[str] = Field(nullable=True, isin=GLUCOSE_BANDS)
    basal_lead_time_min: Series[int] = Field(nullable=True, ge=0)
    basal_lead_time_bucket: Series[str] = Field(isin=BASAL_LEAD_TIME_BUCKETS)
    insulin_on_board_in_going: Series[float] = Field(nullable=True, ge=0)
    total_carbohydrates_g: Series[int] = Field(nullable=True, gt=0)
    earliest_time_before_start_min: Series[int] = Field(nullable=True, le=0)
    avg_bolus_percentage: Series[float] = Field(nullable=True, ge=0)


class PatternAggregateSchema(DataFrameModel):
    bucket_key: Series[str]
    bucket_dim: Series[str] = Field(isin=PATTERN_AGGREGATE_DIMS)
    n: Series[int] = Field(ge=0)
    tir_median: Series[float] = Field(nullable=True, ge=0, le=100)
    tir_mean: Series[float] = Field(nullable=True, ge=0, le=100)
    low_event_rate: Series[float] = Field(nullable=True, ge=0, le=1)
    good_finish_rate: Series[float] = Field(nullable=True, ge=0, le=1)
    stable_20_rate: Series[float] = Field(nullable=True, ge=0, le=1)
    variability_median: Series[float] = Field(nullable=True, ge=0)
    actionable: Series[bool]
