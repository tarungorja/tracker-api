from datetime import datetime
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from app.db.base import as_object_id, created_stamps, now, updated_stamp


class SessionRepository:
    """A signed-in device.

    `tokenHash` is the access token, and `expiresAt` is when the whole session ends (a TTL index
    deletes the row then). Sessions that use refresh tokens also have `accessExpiresAt` (the
    access token is only good until then) and `refreshHash`; the previous refresh token is kept
    in `previousRefreshHash` so a replayed (stolen) one can be detected. Older sessions have none
    of these: their single token simply lasts until `expiresAt`.
    """

    def __init__(self, db: AsyncDatabase) -> None:
        self._col = db.sessions

    async def create(
        self,
        token_hash: str,
        user_id: str | ObjectId,
        expires_at: datetime,
        *,
        access_expires_at: datetime | None = None,
        refresh_hash: str | None = None,
    ) -> None:
        doc: dict[str, Any] = {
            "tokenHash": token_hash,
            "userId": as_object_id(user_id),
            "expiresAt": expires_at,
            **created_stamps(now()),
        }
        if refresh_hash is not None and access_expires_at is not None:
            doc["accessExpiresAt"] = access_expires_at
            doc["refreshHash"] = refresh_hash
        await self._col.insert_one(doc)

    async def find_active_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        moment = now()
        return await self._col.find_one(
            {
                "tokenHash": token_hash,
                "expiresAt": {"$gt": moment},
                "$or": [
                    {"accessExpiresAt": {"$exists": False}},
                    {"accessExpiresAt": {"$gt": moment}},
                ],
            }
        )

    async def rotate(
        self,
        refresh_hash: str,
        new_token_hash: str,
        new_refresh_hash: str,
        access_expires_at: datetime,
        expires_at: datetime,
        moment: datetime,
    ) -> dict[str, Any] | None:
        """Atomically swaps in a new access/refresh pair if `refresh_hash` is the current one.

        Returns the updated session, or None when that refresh token isn't current (unknown,
        expired, or already used), so two requests can never both rotate the same token.
        """
        return await self._col.find_one_and_update(
            {"refreshHash": refresh_hash, "expiresAt": {"$gt": moment}},
            {
                "$set": {
                    "tokenHash": new_token_hash,
                    "accessExpiresAt": access_expires_at,
                    "refreshHash": new_refresh_hash,
                    "previousRefreshHash": refresh_hash,
                    "refreshedAt": moment,
                    "expiresAt": expires_at,
                    **updated_stamp(moment),
                }
            },
            return_document=ReturnDocument.AFTER,
        )

    async def find_by_previous_refresh_hash(self, refresh_hash: str) -> dict[str, Any] | None:
        return await self._col.find_one({"previousRefreshHash": refresh_hash})

    async def delete_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        return await self._col.find_one_and_delete({"tokenHash": token_hash})

    async def delete_by_refresh_hash(self, refresh_hash: str) -> dict[str, Any] | None:
        return await self._col.find_one_and_delete({"refreshHash": refresh_hash})

    async def delete_by_id(self, session_id: str | ObjectId) -> None:
        await self._col.delete_one({"_id": as_object_id(session_id)})

    async def active_ids_for_user(self, user_id: str | ObjectId) -> list[ObjectId]:
        """Sessions that can still sign in (their refresh token, or legacy token, is valid)."""
        cursor = self._col.find(
            {"userId": as_object_id(user_id), "expiresAt": {"$gt": now()}}, {"_id": 1}
        )
        return [doc["_id"] async for doc in cursor]

    async def delete_all_for_user(self, user_id: str | ObjectId) -> int:
        """Signs the user out everywhere."""
        result = await self._col.delete_many({"userId": as_object_id(user_id)})
        return result.deleted_count
