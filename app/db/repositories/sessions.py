from datetime import datetime
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.db.base import as_object_id, created_stamps, now


class SessionRepository:
    def __init__(self, db: AsyncDatabase) -> None:
        self._col = db.sessions

    async def create(self, token_hash: str, user_id: str | ObjectId, expires_at: datetime) -> None:
        await self._col.insert_one(
            {
                "tokenHash": token_hash,
                "userId": as_object_id(user_id),
                "expiresAt": expires_at,
                **created_stamps(now()),
            }
        )

    async def find_active_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        return await self._col.find_one({"tokenHash": token_hash, "expiresAt": {"$gt": now()}})

    async def delete_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        return await self._col.find_one_and_delete({"tokenHash": token_hash})

    async def active_ids_for_user(self, user_id: str | ObjectId) -> list[ObjectId]:
        cursor = self._col.find(
            {"userId": as_object_id(user_id), "expiresAt": {"$gt": now()}}, {"_id": 1}
        )
        return [doc["_id"] async for doc in cursor]
