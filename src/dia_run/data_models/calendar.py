from pydantic import BaseModel, Field


class Calendar(BaseModel):
    distance: list[list[None | float]] = Field(min_length=7)
    dates: list[list[None | str]] = Field(min_length=7)


class CalendarWeek(BaseModel):
    distance: list[None | float] = Field(min_length=7, max_length=7)
    dates: list[None | str] = Field(min_length=7, max_length=7)
