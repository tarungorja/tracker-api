from pydantic import Field

from app.schemas.common import CamelModel, DateKey


class DoseView(CamelModel):
    medication_name: str
    scheduled_time: str
    scheduled_minutes: int
    completed: bool
    completed_at: str | None


class DoseCompletionInput(CamelModel):
    medication_name: str = Field(min_length=1)
    scheduled_time: str = Field(min_length=1)
    completed: bool
    date: DateKey | None = None


class DayCompletion(CamelModel):
    date: str
    total: int
    completed: int
    ratio: float
