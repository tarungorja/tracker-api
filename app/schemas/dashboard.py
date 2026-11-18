from app.schemas.common import CamelModel
from app.schemas.dose import DayCompletion, DoseView
from app.schemas.medication import MedicationView


class NextReminder(CamelModel):
    medication_name: str
    scheduled_time: str
    minutes_until: int
    is_tomorrow: bool


class DashboardData(CamelModel):
    today_key: str
    now_minutes: int
    doses: list[DoseView]
    total_today: int
    completed_today: int
    remaining_today: int
    progress: int
    current_streak: int
    next_reminder: NextReminder | None
    medications: list[MedicationView]
    heatmap: list[DayCompletion]
