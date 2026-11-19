from typing import Any

from bson import ObjectId
from pymongo import DESCENDING
from pymongo.asynchronous.database import AsyncDatabase

from app.db.base import as_object_id, now


class MedicationActivityRepository:
    """Short audit trail (kept 30 days) of changes a user made to their medication list."""

    def __init__(self, db: AsyncDatabase) -> None:
        self._col = db.medicationactivities

    async def record(self, user_id: str | ObjectId, action: str, medication_name: str) -> None:
        await self._col.insert_one(
            {
                "userId": as_object_id(user_id),
                "action": action,
                "medicationName": medication_name,
                "createdAt": now(),
            }
        )

    async def recent(self, user_id: str | ObjectId, limit: int) -> list[dict[str, Any]]:
        return (
            await self._col.find({"userId": as_object_id(user_id)})
            .sort("createdAt", DESCENDING)
            .limit(limit)
            .to_list(None)
        )

    async def delete_all_for_user(self, user_id: str | ObjectId) -> int:
        result = await self._col.delete_many({"userId": as_object_id(user_id)})
        return result.deleted_count
