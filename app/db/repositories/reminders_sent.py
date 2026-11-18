from collections.abc import Iterable

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.db.base import DuplicateKeyError, as_object_id, now


class ReminderSentRepository:
    """Records sent reminders so overlapping cron runs never notify twice."""

    def __init__(self, db: AsyncDatabase) -> None:
        self._col = db.remindersents

    async def claim(
        self, user_id: str | ObjectId, date: str, medication_name: str, scheduled_time: str
    ) -> bool:
        """Atomic claim via the unique index. False means it was already reminded."""
        try:
            await self._col.insert_one(
                {
                    "userId": as_object_id(user_id),
                    "date": date,
                    "medicationName": medication_name,
                    "scheduledTime": scheduled_time,
                    "createdAt": now(),
                }
            )
        except DuplicateKeyError:
            return False
        return True

    async def release(
        self,
        user_id: str | ObjectId,
        date: str,
        scheduled_time: str,
        medication_names: Iterable[str],
    ) -> None:
        await self._col.delete_many(
            {
                "userId": as_object_id(user_id),
                "date": date,
                "scheduledTime": scheduled_time,
                "medicationName": {"$in": list(medication_names)},
            }
        )
