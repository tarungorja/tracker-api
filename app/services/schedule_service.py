"""Shared read model: medications, the doses due on a day, and per-day completion."""

from typing import Any

from bson import ObjectId

from app.db.repositories import DailyLogRepository, MedicationRepository
from app.schemas.dose import DayCompletion, DoseView
from app.schemas.medication import MedicationView
from app.utils.schedule import is_medication_due_on, normalize_days
from app.utils.time import date_key_range, parse_schedule_to_minutes, to_iso_z


def medication_to_view(doc: dict[str, Any]) -> MedicationView:
    times = sorted(doc.get("scheduleTimes") or [], key=lambda t: parse_schedule_to_minutes(t) or 0)
    return MedicationView(
        id=str(doc["_id"]),
        name=doc["name"],
        description=doc.get("description") or "",
        instructions=doc.get("instructions") or "",
        schedule_times=times,
        days_of_week=normalize_days(doc.get("daysOfWeek")),
        enabled=bool(doc.get("enabled")),
    )


class ScheduleService:
    def __init__(self, medications: MedicationRepository, logs: DailyLogRepository) -> None:
        self._medications = medications
        self._logs = logs

    async def medication_views(
        self, user_id: str | ObjectId, only_enabled: bool = False
    ) -> list[MedicationView]:
        docs = await self._medications.list_for_user(user_id, only_enabled)
        return [medication_to_view(doc) for doc in docs]

    async def doses_for_day(self, user_id: str | ObjectId, date_key: str) -> list[DoseView]:
        meds = await self.medication_views(user_id, only_enabled=True)
        logs = await self._logs.find_doses_for_day(user_id, date_key)
        by_key = {(log["medicationName"], log["scheduledTime"]): log for log in logs}

        doses: list[DoseView] = []
        for med in meds:
            if not is_medication_due_on(med.days_of_week, date_key):
                continue
            for time in med.schedule_times:
                log = by_key.get((med.name, time))
                completed_at = log.get("completedAt") if log else None
                doses.append(
                    DoseView(
                        medication_name=med.name,
                        scheduled_time=time,
                        scheduled_minutes=parse_schedule_to_minutes(time) or 0,
                        completed=bool(log and log.get("completed")),
                        completed_at=to_iso_z(completed_at) if completed_at else None,
                    )
                )
        return sorted(doses, key=lambda d: d.scheduled_minutes)

    async def completion_map(
        self, user_id: str | ObjectId, start_key: str, end_key: str
    ) -> dict[str, DayCompletion]:
        """One entry per day in [start, end]; days without logs are zeroed."""
        rows = await self._logs.completion_by_date(user_id, start_key, end_key)
        result = {
            key: DayCompletion(date=key, total=0, completed=0, ratio=0)
            for key in date_key_range(start_key, end_key)
        }
        for row in rows:
            total, completed = row["total"], row["completed"]
            result[row["_id"]] = DayCompletion(
                date=row["_id"],
                total=total,
                completed=completed,
                ratio=completed / total if total > 0 else 0,
            )
        return result
