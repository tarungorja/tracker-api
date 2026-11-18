from pydantic import field_validator

from app.schemas.common import CamelModel, DateKey


class CountPoint(CamelModel):
    date: str
    label: str
    count: int


class HistoryEntry(CamelModel):
    date: str
    label: str
    count: int
    notes: str


class WellnessData(CamelModel):
    today_key: str
    today_count: int
    today_notes: str
    weekly: list[CountPoint]
    monthly: list[CountPoint]
    calendar: list[CountPoint]
    history: list[HistoryEntry]
    total_this_year: int
    average_per_week: float
    longest_clean_streak: int
    current_clean_streak: int
    total_tracked: int


class NotesInput(CamelModel):
    notes: str
    date: DateKey | None = None

    @field_validator("notes")
    @classmethod
    def _check_notes(cls, value: str) -> str:
        if len(value) > 1000:
            raise ValueError("Invalid note.")
        return value
