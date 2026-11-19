from datetime import datetime
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.db.base import as_object_id, now


class InviteCodeRepository:
    """One live, single-use invite code per patient. Only the hash of the code is stored."""

    def __init__(self, db: AsyncDatabase) -> None:
        self._col = db.invitecodes

    async def replace_for_patient(
        self, patient_id: str | ObjectId, code_hash: str, expires_at: datetime
    ) -> None:
        await self._col.replace_one(
            {"patientId": as_object_id(patient_id)},
            {
                "patientId": as_object_id(patient_id),
                "codeHash": code_hash,
                "expiresAt": expires_at,
                "createdAt": now(),
            },
            upsert=True,
        )

    async def consume(self, code_hash: str) -> dict[str, Any] | None:
        """Atomically removes and returns the unexpired invite, so a code works only once."""
        return await self._col.find_one_and_delete(
            {"codeHash": code_hash, "expiresAt": {"$gt": now()}}
        )

    async def delete_all_for_user(self, user_id: str | ObjectId) -> int:
        result = await self._col.delete_many({"patientId": as_object_id(user_id)})
        return result.deleted_count
