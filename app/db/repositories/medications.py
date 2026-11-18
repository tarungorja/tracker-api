from collections.abc import Iterable
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from app.db.base import as_object_id, created_stamps, now, updated_stamp


class MedicationRepository:
    def __init__(self, db: AsyncDatabase) -> None:
        self._col = db.medications

    async def list_for_user(
        self, user_id: str | ObjectId, only_enabled: bool = False
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"userId": as_object_id(user_id)}
        if only_enabled:
            query["enabled"] = True
        return await self._col.find(query).sort("name", 1).to_list(None)

    async def list_enabled_for_users(self, user_ids: Iterable[ObjectId]) -> list[dict[str, Any]]:
        return await self._col.find({"userId": {"$in": list(user_ids)}, "enabled": True}).to_list(
            None
        )

    async def create(self, user_id: str | ObjectId, fields: dict[str, Any]) -> dict[str, Any]:
        """Raises DuplicateKeyError when the user already has a medication with this name."""
        doc = {"userId": as_object_id(user_id), **fields, "enabled": True, **created_stamps(now())}
        result = await self._col.insert_one(doc)
        return {**doc, "_id": result.inserted_id}

    async def update(
        self, user_id: str | ObjectId, medication_id: str | ObjectId, fields: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Returns the updated document, or None when it doesn't exist for this user."""
        return await self._col.find_one_and_update(
            {"_id": as_object_id(medication_id), "userId": as_object_id(user_id)},
            {"$set": {**fields, **updated_stamp(now())}},
            return_document=ReturnDocument.AFTER,
        )

    async def delete(self, user_id: str | ObjectId, medication_id: str | ObjectId) -> bool:
        result = await self._col.delete_one(
            {"_id": as_object_id(medication_id), "userId": as_object_id(user_id)}
        )
        return result.deleted_count > 0

    async def delete_all_for_user(self, user_id: str | ObjectId) -> int:
        """Account deletion: removes every medication the user owns."""
        result = await self._col.delete_many({"userId": as_object_id(user_id)})
        return result.deleted_count
