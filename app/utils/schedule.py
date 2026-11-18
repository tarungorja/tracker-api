from collections.abc import Iterable
from typing import Literal

from app.utils.time import ALL_DAYS, weekday_of_key

DoseStatus = Literal["completed", "pending", "upcoming", "missed"]


def normalize_days(days: Iterable[int] | None) -> list[int]:
    """Valid, de-duplicated, sorted weekdays. Legacy medications with none mean every day."""
    valid = sorted({d for d in (days or []) if 0 <= d <= 6})
    return valid or list(ALL_DAYS)


def is_medication_due_on(days_of_week: Iterable[int], date_key: str) -> bool:
    return weekday_of_key(date_key) in set(days_of_week)


def dose_status(
    completed: bool, scheduled_minutes: int, now_minutes: int, is_today: bool
) -> DoseStatus:
    if completed:
        return "completed"
    if not is_today:
        return "missed"
    return "upcoming" if scheduled_minutes > now_minutes else "missed"
