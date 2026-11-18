from datetime import datetime
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase


class OtpRepository:
    def __init__(self, db: AsyncDatabase) -> None:
        self._col = db.otps

    async def find(self, email: str, purpose: str) -> dict[str, Any] | None:
        return await self._col.find_one({"email": email, "purpose": purpose})

    async def upsert(
        self,
        email: str,
        purpose: str,
        code_hash: str,
        sent_at: datetime,
        expires_at: datetime,
    ) -> None:
        """One active OTP per email + purpose; a new request replaces the old one."""
        await self._col.update_one(
            {"email": email, "purpose": purpose},
            {
                "$set": {
                    "codeHash": code_hash,
                    "attempts": 0,
                    "sentAt": sent_at,
                    "expiresAt": expires_at,
                    "updatedAt": sent_at,
                },
                "$setOnInsert": {"createdAt": sent_at},
            },
            upsert=True,
        )

    async def delete(self, email: str, purpose: str) -> None:
        await self._col.delete_one({"email": email, "purpose": purpose})

    async def delete_by_id(self, otp_id: ObjectId) -> None:
        await self._col.delete_one({"_id": otp_id})

    async def increment_attempts(self, otp_id: ObjectId) -> int | None:
        """Atomically counts one verification attempt and returns the new total.

        Atomic so that many parallel guesses can't all read the same stale count. None means the
        code no longer exists (expired, consumed or locked out).
        """
        doc = await self._col.find_one_and_update(
            {"_id": otp_id},
            {"$inc": {"attempts": 1}},
            return_document=ReturnDocument.AFTER,
            projection={"attempts": 1},
        )
        return None if doc is None else int(doc["attempts"])

    async def consume(self, otp_id: ObjectId) -> bool:
        """Atomically deletes the OTP. False means another request already consumed it."""
        return await self._col.find_one_and_delete({"_id": otp_id}) is not None
