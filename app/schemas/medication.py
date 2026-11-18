from pydantic import field_validator

from app.schemas.common import CamelModel
from app.utils.time import parse_schedule_to_minutes


class MedicationView(CamelModel):
    id: str
    name: str
    description: str
    instructions: str
    schedule_times: list[str]
    days_of_week: list[int]
    enabled: bool


class MedicationInput(CamelModel):
    name: str
    description: str = ""
    instructions: str = ""
    schedule_times: list[str]
    days_of_week: list[int]

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required.")
        if len(value) > 120:
            raise ValueError("Name is too long (max 120 characters).")
        return value

    @field_validator("description")
    @classmethod
    def _check_description(cls, value: str) -> str:
        if len(value) > 300:
            raise ValueError("Description is too long (max 300 characters).")
        return value

    @field_validator("instructions")
    @classmethod
    def _check_instructions(cls, value: str) -> str:
        if len(value) > 2000:
            raise ValueError("Instructions are too long (max 2000 characters).")
        return value

    @field_validator("schedule_times")
    @classmethod
    def _check_times(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("Add at least one time.")
        if any(parse_schedule_to_minutes(t) is None for t in value):
            raise ValueError("Enter a valid time.")
        return value

    @field_validator("days_of_week")
    @classmethod
    def _check_days(cls, value: list[int]) -> list[int]:
        if not value or len(value) > 7 or any(d < 0 or d > 6 for d in value):
            raise ValueError("Pick at least one day of the week.")
        return value


class MedicationEnabledInput(CamelModel):
    enabled: bool


class MedHistoryDay(CamelModel):
    date: str
    total: int
    completed: int
    ratio: float


class MedTodayDose(CamelModel):
    time: str
    minutes: int
    completed: bool


class MedicationWithHistory(MedicationView):
    today_doses: list[MedTodayDose]
    completed_today: int
    total_today: int
    history: list[MedHistoryDay]


class MedicationsPageData(CamelModel):
    today_key: str
    now_minutes: int
    medications: list[MedicationWithHistory]
