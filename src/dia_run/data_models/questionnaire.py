from pydantic import BaseModel, Field


class PreRunInfo(BaseModel):
    carbohydrates_g: int = Field(gt=0)
    time_before_start_min: int = Field(le=0)
    bolus_percentage: float = Field(ge=0)
    food_type: str


class BasalAdjustment(BaseModel):
    type: str
    start_time_min: int
    end_time_min: int
    basal_rate_percentage: float | None = Field(default=None, ge=0)


class FuelingEntry(BaseModel):
    carbohydrates_g: int = Field(gt=0)
    time_during_run_min: int = Field(ge=0)
    food_type: str


class BolusEntry(BaseModel):
    time_of_bolus_min: int
    bolus_units: float = Field(gt=0)


class QuestionnaireModel(BaseModel):
    pre_run: list[PreRunInfo] = Field(default_factory=list)
    basal_adjustments: list[BasalAdjustment] = Field(default_factory=list)
    fueling_during_run: list[FuelingEntry] = Field(default_factory=list)
    bolus: list[BolusEntry] = Field(default_factory=list)
