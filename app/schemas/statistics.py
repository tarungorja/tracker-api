from app.schemas.common import CamelModel
from app.schemas.dose import DayCompletion


class MedicationStat(CamelModel):
    name: str
    total: int
    completed: int
    percent: int


class StatisticsData(CamelModel):
    today_key: str
    overall_percent: int
    overall_completed: int
    overall_total: int
    month_percent: int
    month_completed: int
    month_total: int
    current_streak: int
    longest_streak: int
    missed_reminders: int
    heatmap: list[DayCompletion]
    medication_stats: list[MedicationStat]
