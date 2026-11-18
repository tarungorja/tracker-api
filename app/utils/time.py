"""IST calendar helpers. Date keys are "YYYY-MM-DD" strings in India Standard Time."""

import re
from datetime import UTC, date, datetime, timedelta, timezone
from typing import NamedTuple

IST = timezone(timedelta(hours=5, minutes=30), "IST")
ALL_DAYS: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)  # 0 = Sunday

_SCHEDULE_RE = re.compile(r"(\d{1,2}):(\d{2})\s*(AM|PM)?", re.IGNORECASE | re.ASCII)
_DATE_KEY_RE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MAX_RANGE_DAYS = 4000


class NowContext(NamedTuple):
    today_key: str
    now_minutes: int


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_ist(moment: datetime | None = None) -> datetime:
    return (moment or utcnow()).astimezone(IST)


def ist_date_key(moment: datetime | None = None) -> str:
    return to_ist(moment).date().isoformat()


def ist_minutes_of_day(moment: datetime | None = None) -> int:
    local = to_ist(moment)
    return local.hour * 60 + local.minute


def now_context(moment: datetime | None = None) -> NowContext:
    return NowContext(ist_date_key(moment), ist_minutes_of_day(moment))


def to_iso_z(moment: datetime) -> str:
    """ISO-8601 UTC with millisecond precision, e.g. 2026-01-05T08:30:00.000Z."""
    utc = moment.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


def parse_schedule_to_minutes(label: str) -> int | None:
    """ "2:30 PM" / "14:30" -> minutes since midnight, or None if invalid."""
    match = _SCHEDULE_RE.fullmatch(label.strip())
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    meridiem = (match.group(3) or "").upper()

    if meridiem == "PM" and hour != 12:
        hour += 12
    if meridiem == "AM" and hour == 12:
        hour = 0

    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def minutes_to_label(minutes: int) -> str:
    hour24 = (minutes // 60) % 24
    minute = minutes % 60
    meridiem = "PM" if hour24 >= 12 else "AM"
    hour12 = 12 if hour24 % 12 == 0 else hour24 % 12
    return f"{hour12}:{minute:02d} {meridiem}"


def normalize_schedule_label(label: str) -> str:
    minutes = parse_schedule_to_minutes(label)
    return label.strip() if minutes is None else minutes_to_label(minutes)


def is_valid_date_key(key: str) -> bool:
    if not _DATE_KEY_RE.fullmatch(key):
        return False
    try:
        date.fromisoformat(key)
    except ValueError:
        return False
    return True


def add_days_to_key(date_key: str, days: int) -> str:
    return (date.fromisoformat(date_key) + timedelta(days=days)).isoformat()


def date_key_range(start_key: str, end_key: str) -> list[str]:
    """Inclusive list of date keys from start to end."""
    keys: list[str] = []
    cursor = start_key
    while cursor <= end_key and len(keys) < _MAX_RANGE_DAYS:
        keys.append(cursor)
        cursor = add_days_to_key(cursor, 1)
    return keys


def days_between_keys(start_key: str, end_key: str) -> int:
    return (date.fromisoformat(end_key) - date.fromisoformat(start_key)).days


def weekday_of_key(date_key: str) -> int:
    """0 = Sunday ... 6 = Saturday."""
    return (date.fromisoformat(date_key).weekday() + 1) % 7


def short_date_label(date_key: str) -> str:
    parsed = date.fromisoformat(date_key)
    return f"{_MONTHS[parsed.month - 1]} {parsed.day}"
