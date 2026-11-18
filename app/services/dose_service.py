from app.db.repositories import DailyLogRepository
from app.schemas.dose import DoseCompletionInput
from app.utils.time import ist_date_key, normalize_schedule_label, utcnow


class DoseService:
    def __init__(self, logs: DailyLogRepository) -> None:
        self._logs = logs

    async def set_completion(self, user_id: str, data: DoseCompletionInput) -> None:
        await self._logs.set_dose_completion(
            user_id,
            date=data.date or ist_date_key(),
            medication_name=data.medication_name,
            scheduled_time=normalize_schedule_label(data.scheduled_time),
            completed=data.completed,
            moment=utcnow(),
        )
