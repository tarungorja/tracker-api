from datetime import datetime

from app.schemas.today import TimelineDose, TimelineSlot, TodayData
from app.services.schedule_service import ScheduleService
from app.utils.schedule import dose_status
from app.utils.time import now_context, parse_schedule_to_minutes


class TodayService:
    def __init__(self, schedule: ScheduleService) -> None:
        self._schedule = schedule

    async def get(self, user_id: str, now: datetime | None = None) -> TodayData:
        today_key, now_minutes = now_context(now)
        doses = await self._schedule.doses_for_day(user_id, today_key)

        slots: dict[str, TimelineSlot] = {}
        for dose in doses:
            entry = TimelineDose(
                **dose.model_dump(),
                status=dose_status(dose.completed, dose.scheduled_minutes, now_minutes, True),
            )
            slot = slots.get(dose.scheduled_time)
            if slot is None:
                slots[dose.scheduled_time] = TimelineSlot(
                    time=dose.scheduled_time,
                    minutes=parse_schedule_to_minutes(dose.scheduled_time) or 0,
                    doses=[entry],
                )
            else:
                slot.doses.append(entry)

        return TodayData(
            today_key=today_key,
            now_minutes=now_minutes,
            slots=sorted(slots.values(), key=lambda s: s.minutes),
            total=len(doses),
            completed=sum(1 for d in doses if d.completed),
        )
