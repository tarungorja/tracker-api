from datetime import datetime
from typing import Any

from app.core.constants import MEDICATION_HISTORY_DAYS
from app.core.exceptions import ConflictError, NotFoundError
from app.db.base import DuplicateKeyError
from app.db.repositories import (
    DailyLogRepository,
    MedicationActivityRepository,
    MedicationRepository,
)
from app.schemas.medication import (
    MedHistoryDay,
    MedicationInput,
    MedicationsPageData,
    MedicationView,
    MedicationWithHistory,
    MedTodayDose,
)
from app.services.schedule_service import ScheduleService, medication_to_view
from app.utils.schedule import is_medication_due_on
from app.utils.time import (
    add_days_to_key,
    date_key_range,
    normalize_schedule_label,
    now_context,
    parse_schedule_to_minutes,
    utcnow,
)

_NOT_FOUND = "Medication not found."
_DUPLICATE = "A medication with that name already exists."


def _fields_from_input(data: MedicationInput) -> dict[str, Any]:
    return {
        "name": data.name,
        "description": data.description,
        "instructions": data.instructions,
        "scheduleTimes": list(
            dict.fromkeys(normalize_schedule_label(t) for t in data.schedule_times)
        ),
        "daysOfWeek": sorted(set(data.days_of_week)),
    }


class MedicationService:
    def __init__(
        self,
        medications: MedicationRepository,
        logs: DailyLogRepository,
        schedule: ScheduleService,
        activity: MedicationActivityRepository,
    ) -> None:
        self._medications = medications
        self._logs = logs
        self._schedule = schedule
        self._activity = activity

    async def page_data(self, user_id: str, now: datetime | None = None) -> MedicationsPageData:
        today_key, now_minutes = now_context(now or utcnow())
        start_key = add_days_to_key(today_key, -(MEDICATION_HISTORY_DAYS - 1))

        meds = await self._schedule.medication_views(user_id, only_enabled=False)
        today_doses = await self._schedule.doses_for_day(user_id, today_key)
        history_rows = await self._logs.find_doses_in_range(user_id, start_key, today_key)

        # medication name -> date -> {total, completed}
        index: dict[str, dict[str, dict[str, int]]] = {}
        for row in history_rows:
            day = index.setdefault(row["medicationName"], {}).setdefault(
                row["date"], {"total": 0, "completed": 0}
            )
            day["total"] += 1
            if row.get("completed"):
                day["completed"] += 1

        day_keys = date_key_range(start_key, today_key)
        today_by_key = {(d.medication_name, d.scheduled_time): d for d in today_doses}

        result: list[MedicationWithHistory] = []
        for med in meds:
            due_today = is_medication_due_on(med.days_of_week, today_key)
            doses = [
                MedTodayDose(
                    time=time,
                    minutes=parse_schedule_to_minutes(time) or 0,
                    completed=bool(
                        (match := today_by_key.get((med.name, time))) and match.completed
                    ),
                )
                for time in med.schedule_times
                if due_today
            ]

            per_med = index.get(med.name, {})
            history: list[MedHistoryDay] = []
            for date in day_keys:
                scheduled = (
                    len(med.schedule_times) if is_medication_due_on(med.days_of_week, date) else 0
                )
                logged = per_med.get(date)
                total = scheduled if date == today_key or logged is None else logged["total"]
                completed = logged["completed"] if logged else 0
                history.append(
                    MedHistoryDay(
                        date=date,
                        total=total,
                        completed=completed,
                        ratio=completed / total if total > 0 else 0,
                    )
                )

            result.append(
                MedicationWithHistory(
                    **med.model_dump(),
                    today_doses=doses,
                    completed_today=sum(1 for d in doses if d.completed),
                    total_today=len(doses),
                    history=history,
                )
            )

        return MedicationsPageData(today_key=today_key, now_minutes=now_minutes, medications=result)

    async def create(self, user_id: str, data: MedicationInput) -> MedicationView:
        try:
            doc = await self._medications.create(user_id, _fields_from_input(data))
        except DuplicateKeyError as exc:
            raise ConflictError(_DUPLICATE) from exc
        await self._activity.record(user_id, "added", doc["name"])
        return medication_to_view(doc)

    async def update(
        self, user_id: str, medication_id: str, data: MedicationInput
    ) -> MedicationView:
        try:
            doc = await self._medications.update(user_id, medication_id, _fields_from_input(data))
        except DuplicateKeyError as exc:
            raise ConflictError(_DUPLICATE) from exc
        if doc is None:
            raise NotFoundError(_NOT_FOUND)
        await self._activity.record(user_id, "updated", doc["name"])
        return medication_to_view(doc)

    async def set_enabled(self, user_id: str, medication_id: str, enabled: bool) -> MedicationView:
        doc = await self._medications.update(user_id, medication_id, {"enabled": enabled})
        if doc is None:
            raise NotFoundError(_NOT_FOUND)
        await self._activity.record(user_id, "enabled" if enabled else "disabled", doc["name"])
        return medication_to_view(doc)

    async def delete(self, user_id: str, medication_id: str) -> None:
        existing = next(
            (
                m
                for m in await self._medications.list_for_user(user_id)
                if str(m["_id"]) == medication_id
            ),
            None,
        )
        if not await self._medications.delete(user_id, medication_id):
            raise NotFoundError(_NOT_FOUND)
        if existing:
            await self._activity.record(user_id, "removed", existing["name"])
