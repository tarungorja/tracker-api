from datetime import datetime

from app.core.constants import STATS_DAYS
from app.db.repositories import DailyLogRepository
from app.schemas.statistics import MedicationStat, StatisticsData
from app.services.schedule_service import ScheduleService
from app.utils.numbers import round_half_up
from app.utils.streaks import current_streak, longest_streak
from app.utils.time import add_days_to_key, now_context


def _percent(completed: int, total: int) -> int:
    return int(round_half_up(completed / total * 100)) if total > 0 else 0


class StatisticsService:
    def __init__(self, logs: DailyLogRepository, schedule: ScheduleService) -> None:
        self._logs = logs
        self._schedule = schedule

    async def get(self, user_id: str, now: datetime | None = None) -> StatisticsData:
        today_key = now_context(now).today_key
        start_key = add_days_to_key(today_key, -(STATS_DAYS - 1))
        month_start_key = f"{today_key[:7]}-01"

        completion = await self._schedule.completion_map(user_id, start_key, today_key)
        med_rows = await self._logs.completion_by_medication(user_id, start_key, today_key)
        missed = await self._logs.count_missed_before(user_id, today_key)

        days = sorted(completion.values(), key=lambda d: d.date)
        overall_completed = sum(d.completed for d in days)
        overall_total = sum(d.total for d in days)
        month_days = [d for d in days if d.date >= month_start_key]
        month_completed = sum(d.completed for d in month_days)
        month_total = sum(d.total for d in month_days)

        def is_day_complete(key: str) -> bool:
            day = completion.get(key)
            return bool(day and day.total > 0 and day.completed >= day.total)

        stats = sorted(
            (
                MedicationStat(
                    name=row["_id"],
                    total=row["total"],
                    completed=row["completed"],
                    percent=_percent(row["completed"], row["total"]),
                )
                for row in med_rows
            ),
            key=lambda s: (-s.percent, s.name),
        )

        return StatisticsData(
            today_key=today_key,
            overall_percent=_percent(overall_completed, overall_total),
            overall_completed=overall_completed,
            overall_total=overall_total,
            month_percent=_percent(month_completed, month_total),
            month_completed=month_completed,
            month_total=month_total,
            current_streak=current_streak(today_key, is_day_complete, True),
            longest_streak=longest_streak([d.date for d in days], is_day_complete),
            missed_reminders=missed,
            heatmap=days,
            medication_stats=stats,
        )
