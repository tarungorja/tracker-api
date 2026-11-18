from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.db.base import as_object_id, created_stamps, now


class UserRepository:
    def __init__(self, db: AsyncDatabase) -> None:
        self._col = db.users

    async def exists_by_email(self, email: str) -> bool:
        return await self._col.find_one({"email": email}, {"_id": 1}) is not None

    async def find_by_email(self, email: str) -> dict[str, Any] | None:
        return await self._col.find_one({"email": email})

    async def find_by_id(self, user_id: str | ObjectId) -> dict[str, Any] | None:
        return await self._col.find_one({"_id": as_object_id(user_id)})

    async def create(self, email: str) -> dict[str, Any]:
        """Raises DuplicateKeyError when the email is already registered."""
        doc = {"email": email, **created_stamps(now())}
        result = await self._col.insert_one(doc)
        return {**doc, "_id": result.inserted_id}

    async def delete(self, user_id: str | ObjectId) -> bool:
        result = await self._col.delete_one({"_id": as_object_id(user_id)})
        return result.deleted_count > 0
