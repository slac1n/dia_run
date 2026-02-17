from pydantic import BaseModel


class KpiModel(BaseModel):
    total_distance_km: float
    total_running_time_minutes: int
    avg_sensor_glucose: float | None
    time_in_range_percentage: float | None

    @property
    def formatted_running_time(self) -> str:
        hours = self.total_running_time_minutes // 60
        minutes = self.total_running_time_minutes % 60
        return f"{hours}h {minutes}m"
