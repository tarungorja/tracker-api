from datetime import datetime

from app.core.constants import HEATMAP_DAYS
from app.schemas.dashboard import DashboardData, NextReminder
from app.schemas.dose import DoseView
from app.services.schedule_service import ScheduleService
from app.utils.numbers import round_half_up
from app.utils.streaks import current_streak
from app.utils.time import add_days_to_key, now_context

_MINUTES_PER_DAY = 24 * 60


def compute_next_reminder(doses: list[DoseView], now_minutes: int) -> NextReminder | None:
    """The next unfinished dose today, otherwise the first dose of tomorrow."""
    pending = sorted((d for d in doses if not d.completed), key=lambda d: d.scheduled_minutes)
    upcoming = next((d for d in pending if d.scheduled_minutes >= now_minutes), None)
    if upcoming:
        return NextReminder(
            medication_name=upcoming.medication_name,
            scheduled_time=upcoming.scheduled_time,
            minutes_until=upcoming.scheduled_minutes - now_minutes,
            is_tomorrow=False,
        )

    if not doses:
        return None
    earliest = min(doses, key=lambda d: d.scheduled_minutes)
    return NextReminder(
        medication_name=earliest.medication_name,
        scheduled_time=earliest.scheduled_time,
        minutes_until=_MINUTES_PER_DAY - now_minutes + earliest.scheduled_minutes,
        is_tomorrow=True,
    )


class DashboardService:
    def __init__(self, schedule: ScheduleService) -> None:
        self._schedule = schedule

    async def get(self, user_id: str, now: datetime | None = None) -> DashboardData:
        today_key, now_minutes = now_context(now)

        doses = await self._schedule.doses_for_day(user_id, today_key)
        medications = await self._schedule.medication_views(user_id, only_enabled=True)
        completion = await self._schedule.completion_map(
            user_id, add_days_to_key(today_key, -(HEATMAP_DAYS - 1)), today_key
        )

        total_today = len(doses)
        completed_today = sum(1 for d in doses if d.completed)
        progress = int(round_half_up(completed_today / total_today * 100)) if total_today > 0 else 0

        # Today's heatmap cell reflects the live schedule rather than only logged rows.
        today = completion.get(today_key)
        if today:
            today.total = max(today.total, total_today)
            today.completed = completed_today
            today.ratio = today.completed / today.total if today.total > 0 else 0

        def is_day_complete(key: str) -> bool:
            day = completion.get(key)
            return bool(day and day.total > 0 and day.completed >= day.total)

        return DashboardData(
            today_key=today_key,
            now_minutes=now_minutes,
            doses=doses,
            total_today=total_today,
            completed_today=completed_today,
            remaining_today=total_today - completed_today,
            progress=progress,
            current_streak=current_streak(today_key, is_day_complete, True),
            next_reminder=compute_next_reminder(doses, now_minutes),
            medications=medications,
            heatmap=sorted(completion.values(), key=lambda d: d.date),
        )
