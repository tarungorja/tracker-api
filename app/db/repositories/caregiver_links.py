from datetime import datetime
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.db.base import as_object_id, now


class CaregiverLinkRepository:
    """`caregiver` (the son) may view and remind `patient` (the father)."""

    def __init__(self, db: AsyncDatabase) -> None:
        self._col = db.caregiverlinks

    async def create(self, caregiver_id: str | ObjectId, patient_id: str | ObjectId) -> None:
        """Idempotent: connecting twice keeps the original link."""
        await self._col.update_one(
            {"caregiverId": as_object_id(caregiver_id), "patientId": as_object_id(patient_id)},
            {"$setOnInsert": {"createdAt": now()}},
            upsert=True,
        )

    async def find(
        self, caregiver_id: str | ObjectId, patient_id: str | ObjectId
    ) -> dict[str, Any] | None:
        return await self._col.find_one(
            {"caregiverId": as_object_id(caregiver_id), "patientId": as_object_id(patient_id)}
        )

    async def list_for_caregiver(self, caregiver_id: str | ObjectId) -> list[dict[str, Any]]:
        return (
            await self._col.find({"caregiverId": as_object_id(caregiver_id)})
            .sort("createdAt", 1)
            .to_list(None)
        )

    async def list_for_patient(self, patient_id: str | ObjectId) -> list[dict[str, Any]]:
        return (
            await self._col.find({"patientId": as_object_id(patient_id)})
            .sort("createdAt", 1)
            .to_list(None)
        )

    async def delete(self, caregiver_id: str | ObjectId, patient_id: str | ObjectId) -> bool:
        result = await self._col.delete_one(
            {"caregiverId": as_object_id(caregiver_id), "patientId": as_object_id(patient_id)}
        )
        return result.deleted_count > 0

    async def claim_reminder(
        self,
        caregiver_id: str | ObjectId,
        patient_id: str | ObjectId,
        cutoff: datetime,
        moment: datetime,
    ) -> bool:
        """Atomically starts the cooldown. False when a reminder was sent after `cutoff`."""
        result = await self._col.update_one(
            {
                "caregiverId": as_object_id(caregiver_id),
                "patientId": as_object_id(patient_id),
                "$or": [
                    {"lastRemindedAt": {"$exists": False}},
                    {"lastRemindedAt": None},
                    {"lastRemindedAt": {"$lte": cutoff}},
                ],
            },
            {"$set": {"lastRemindedAt": moment}},
        )
        return result.modified_count > 0

    async def release_reminder(
        self, caregiver_id: str | ObjectId, patient_id: str | ObjectId, moment: datetime
    ) -> None:
        """Undoes `claim_reminder` when nothing was delivered, so the user can retry."""
        await self._col.update_one(
            {
                "caregiverId": as_object_id(caregiver_id),
                "patientId": as_object_id(patient_id),
                "lastRemindedAt": moment,
            },
            {"$set": {"lastRemindedAt": None}},
        )

    async def delete_all_for_user(self, user_id: str | ObjectId) -> int:
        """Account deletion: drops links in which the user is either side."""
        uid = as_object_id(user_id)
        result = await self._col.delete_many({"$or": [{"caregiverId": uid}, {"patientId": uid}]})
        return result.deleted_count
