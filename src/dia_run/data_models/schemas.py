from datetime import datetime

from pandera.polars import DataFrameModel, Field
from pandera.typing import Series

from dia_run.data_models.run_types import RunType


class SummarySchema(DataFrameModel):
    activity_id: Series[int] = Field(unique=True)
    name: Series[str]
    start_date_local: Series[datetime]
    distance: Series[float] = Field(ge=0)
    moving_time: Series[int] = Field(ge=0)
    elapsed_time: Series[int] = Field(ge=0)
    total_elevation_gain: Series[float] = Field(ge=0)
    average_heartrate: Series[float] = Field(ge=0)
    max_heartrate: Series[int] = Field(ge=0)
    average_speed: Series[float] = Field(ge=0)
    max_speed: Series[float] = Field(ge=0)
    average_watts: Series[float] = Field(ge=0)
    max_watts: Series[int] = Field(ge=0)
    kilojoules: Series[float] = Field(ge=0)
    average_pace: Series[float] = Field(ge=0)
    max_pace: Series[float] = Field(ge=0)
    human_readable_time: Series[str]
    human_readable_pace: Series[str]
    distance_in_km: Series[str]
    end_date_local: Series[datetime]
    name_date: Series[str]
    date: Series[str]
    run_type: Series[str] = Field(isin=[rt.value for rt in RunType])
    in_going_sg: Series[float] = Field(nullable=True, gt=0)
    out_going_sg: Series[float] = Field(nullable=True, gt=0)
    avg_sg: Series[float] = Field(nullable=True, gt=0)
    insulin_on_board_in_going: Series[float] = Field(ge=0)


class SpecificCarelinkSchema(DataFrameModel):
    datetime: Series[datetime]
    type: Series[str] = Field(isin=["CGM", "AUTO_BASAL_DELIVERY", "INSULIN"])
    value: Series[float] = Field(nullable=True, gt=0)
