from datetime import datetime
from typing import Any, Sequence

from pydantic import BaseModel, Field, field_validator


class StravaActivitySummary(BaseModel):
    id: int
    name: str
    start_date_local: datetime
    distance: float = Field(ge=0)
    moving_time: int = Field(ge=0)
    elapsed_time: int = Field(ge=0)
    total_elevation_gain: float = Field(ge=0)
    average_heartrate: float | None = Field(default=None, ge=0)
    max_heartrate: float | None = Field(default=None, ge=0)
    average_speed: float | None = Field(default=None, ge=0)
    max_speed: float | None = Field(default=None, ge=0)
    average_watts: float | None = Field(default=None, ge=0)
    max_watts: float | None = Field(default=None, ge=0)
    kilojoules: float | None = Field(default=None, ge=0)
    type: str = "Run"

    @field_validator("type")
    @classmethod
    def validate_run_type(cls, v: str) -> str:
        if v != "Run":
            raise ValueError(f"Activity type must be 'Run', got '{v}'")
        return v


class StravaStreamData(BaseModel):
    time: Sequence[int]
    heartrate: Sequence[int | None]
    watts: Sequence[float | None]
    velocity_smooth: Sequence[float | None]
    moving: Sequence[bool | None]


class CareLinkGlucoseReading(BaseModel):
    timestamp: str
    sg: float | None = Field(default=None, ge=0)

    @field_validator("sg")
    @classmethod
    def validate_glucose(cls, v: float | None) -> float | None:
        if v == 0:
            return None
        if v is not None and v < 20:
            raise ValueError(f"Glucose value {v} seems invalid (too low)")
        if v is not None and v > 600:
            raise ValueError(f"Glucose value {v} seems invalid (too high)")
        return v


class CareLinkMarker(BaseModel):
    timestamp: str
    type: str = Field(
        pattern="^(AUTO_BASAL_DELIVERY|INSULIN|BOLUS|MEAL_SUMMARY|EXERCISE|SMBG|AUTO_MODE_STATUS|MEAL|LOW_GLUCOSE_SUSPENDED|BG_READING)$"
    )
    data: dict[str, Any]


class CareLinkPatientData(BaseModel):
    sgs: list[CareLinkGlucoseReading]
    markers: list[CareLinkMarker]


class CareLinkResponse(BaseModel):
    patientData: CareLinkPatientData
