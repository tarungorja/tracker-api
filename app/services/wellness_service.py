from datetime import datetime

from app.core.constants import (
    WELLNESS_CALENDAR_DAYS,
    WELLNESS_HISTORY_LIMIT,
    WELLNESS_WEEKLY_AVG_WINDOW,
    WELLNESS_YEAR_DAYS,
)
from app.db.repositories import DailyLogRepository
from app.schemas.wellness import CountPoint, HistoryEntry, WellnessData
from app.utils.numbers import round_half_up
from app.utils.time import (
    add_days_to_key,
    date_key_range,
    days_between_keys,
    ist_date_key,
    now_context,
    short_date_label,
    utcnow,
)


class WellnessService:
    def __init__(self, logs: DailyLogRepository) -> None:
        self._logs = logs

    # ---- mutations -------------------------------------------------------------------------

    async def increment(self, user_id: str, date: str | None) -> int:
        return await self._logs.adjust_wellness_count(user_id, date or ist_date_key(), 1, utcnow())

    async def decrement(self, user_id: str, date: str | None) -> int:
        return await self._logs.adjust_wellness_count(user_id, date or ist_date_key(), -1, utcnow())

    async def reset(self, user_id: str, date: str | None) -> int:
        await self._logs.reset_wellness_count(user_id, date or ist_date_key(), utcnow())
        return 0

    async def set_notes(self, user_id: str, notes: str, date: str | None) -> None:
        await self._logs.set_wellness_notes(user_id, date or ist_date_key(), notes, utcnow())

    # ---- read model ------------------------------------------------------------------------

    async def get(self, user_id: str, now: datetime | None = None) -> WellnessData:
        today_key = now_context(now).today_key
        range_start = add_days_to_key(today_key, -(WELLNESS_YEAR_DAYS - 1))
        logs = await self._logs.find_wellness_range(user_id, range_start, today_key)

        counts: dict[str, int] = {}
        notes: dict[str, str] = {}
        for log in logs:
            counts[log["date"]] = log.get("count") or 0
            if log.get("notes"):
                notes[log["date"]] = log["notes"]

        def point(date: str) -> CountPoint:
            return CountPoint(date=date, label=short_date_label(date), count=counts.get(date, 0))

        def window(days: int) -> list[CountPoint]:
            return [
                point(d) for d in date_key_range(add_days_to_key(today_key, -(days - 1)), today_key)
            ]

        history = [
            HistoryEntry(
                date=log["date"],
                label=short_date_label(log["date"]),
                count=log.get("count") or 0,
                notes=log.get("notes") or "",
            )
            for log in sorted(
                (lg for lg in logs if (lg.get("count") or 0) > 0 or lg.get("notes")),
                key=lambda lg: lg["date"],
                reverse=True,
            )[:WELLNESS_HISTORY_LIMIT]
        ]

        year_start = f"{today_key[:4]}-01-01"
        total_tracked = sum(counts.values())
        total_this_year = sum(c for d, c in counts.items() if d >= year_start)

        avg_keys = date_key_range(
            add_days_to_key(today_key, -(WELLNESS_WEEKLY_AVG_WINDOW - 1)), today_key
        )
        window_total = sum(counts.get(d, 0) for d in avg_keys)
        average_per_week = round_half_up(window_total / (WELLNESS_WEEKLY_AVG_WINDOW / 7), 1)

        def is_clean(key: str) -> bool:
            return counts.get(key, 0) == 0

        earliest_logged = next((lg["date"] for lg in logs if (lg.get("count") or 0) > 0), today_key)
        floor = min(earliest_logged, today_key)

        current_clean = 0
        cursor = today_key
        while cursor >= floor and is_clean(cursor):
            current_clean += 1
            cursor = add_days_to_key(cursor, -1)

        longest_clean = 0
        run = 0
        for key in date_key_range(earliest_logged, today_key):
            if is_clean(key):
                run += 1
                longest_clean = max(longest_clean, run)
            else:
                run = 0

        if all((lg.get("count") or 0) == 0 for lg in logs):
            span = days_between_keys(floor, today_key) + 1
            longest_clean = max(longest_clean, span if span > 0 else 1)
            current_clean = longest_clean

        return WellnessData(
            today_key=today_key,
            today_count=counts.get(today_key, 0),
            today_notes=notes.get(today_key, ""),
            weekly=window(7),
            monthly=window(30),
            calendar=window(WELLNESS_CALENDAR_DAYS),
            history=history,
            total_this_year=total_this_year,
            average_per_week=average_per_week,
            longest_clean_streak=longest_clean,
            current_clean_streak=current_clean,
            total_tracked=total_tracked,
        )
