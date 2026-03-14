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
