"""Dose logs and wellness counters. Both live in `dailylogs`; wellness rows use a sentinel name."""

from datetime import datetime
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from app.core.constants import WELLNESS_LOG_KEY
from app.db.base import as_object_id

_NOT_WELLNESS = {"$ne": WELLNESS_LOG_KEY}


class DailyLogRepository:
    def __init__(self, db: AsyncDatabase) -> None:
        self._col = db.dailylogs

    # ---- dose logs -------------------------------------------------------------------------

    async def set_dose_completion(
        self,
        user_id: str | ObjectId,
        date: str,
        medication_name: str,
        scheduled_time: str,
        completed: bool,
        moment: datetime,
    ) -> None:
        await self._col.update_one(
            {
                "userId": as_object_id(user_id),
                "date": date,
                "medicationName": medication_name,
                "scheduledTime": scheduled_time,
            },
            {
                "$set": {
                    "completed": completed,
                    "completedAt": moment if completed else None,
                    "updatedAt": moment,
                },
                "$setOnInsert": {"createdAt": moment, "notes": "", "count": 0},
            },
            upsert=True,
        )

    async def is_dose_completed(
        self, user_id: str | ObjectId, date: str, medication_name: str, scheduled_time: str
    ) -> bool:
        found = await self._col.find_one(
            {
                "userId": as_object_id(user_id),
                "date": date,
                "medicationName": medication_name,
                "scheduledTime": scheduled_time,
                "completed": True,
            },
            {"_id": 1},
        )
        return found is not None

    async def find_doses_for_day(self, user_id: str | ObjectId, date: str) -> list[dict[str, Any]]:
        return await self._col.find(
            {"userId": as_object_id(user_id), "date": date, "medicationName": _NOT_WELLNESS}
        ).to_list(None)

    async def find_doses_in_range(
        self, user_id: str | ObjectId, start: str, end: str
    ) -> list[dict[str, Any]]:
        return await self._col.find(
            {
                "userId": as_object_id(user_id),
                "date": {"$gte": start, "$lte": end},
                "medicationName": _NOT_WELLNESS,
            }
        ).to_list(None)

    async def completion_by_date(
        self, user_id: str | ObjectId, start: str, end: str
    ) -> list[dict[str, Any]]:
        return await self._group_doses(user_id, start, end, "$date")

    async def completion_by_medication(
        self, user_id: str | ObjectId, start: str, end: str
    ) -> list[dict[str, Any]]:
        return await self._group_doses(user_id, start, end, "$medicationName")

    async def count_missed_before(self, user_id: str | ObjectId, date: str) -> int:
        return await self._col.count_documents(
            {
                "userId": as_object_id(user_id),
                "completed": False,
                "date": {"$lt": date},
                "medicationName": _NOT_WELLNESS,
            }
        )

    async def _group_doses(
        self, user_id: str | ObjectId, start: str, end: str, group_by: str
    ) -> list[dict[str, Any]]:
        cursor = await self._col.aggregate(
            [
                {
                    "$match": {
                        "userId": as_object_id(user_id),
                        "date": {"$gte": start, "$lte": end},
                        "medicationName": _NOT_WELLNESS,
                    }
                },
                {
                    "$group": {
                        "_id": group_by,
                        "total": {"$sum": 1},
                        "completed": {"$sum": {"$cond": ["$completed", 1, 0]}},
                    }
                },
            ]
        )
        return await cursor.to_list(None)

    # ---- wellness --------------------------------------------------------------------------

    @staticmethod
    def _wellness_key(user_id: str | ObjectId, day: str) -> dict[str, Any]:
        return {
            "userId": as_object_id(user_id),
            "date": day,
            "medicationName": WELLNESS_LOG_KEY,
            "scheduledTime": WELLNESS_LOG_KEY,
        }

    async def find_wellness_range(
        self, user_id: str | ObjectId, start: str, end: str
    ) -> list[dict[str, Any]]:
        return (
            await self._col.find(
                {
                    "userId": as_object_id(user_id),
                    "medicationName": WELLNESS_LOG_KEY,
                    "date": {"$gte": start, "$lte": end},
                }
            )
            .sort("date", 1)
            .to_list(None)
        )

    async def adjust_wellness_count(
        self, user_id: str | ObjectId, day: str, delta: int, moment: datetime
    ) -> int:
        """Atomically adds `delta` (never dropping below zero) and returns the new count."""
        doc = await self._col.find_one_and_update(
            self._wellness_key(user_id, day),
            [
                {
                    "$set": {
                        "count": {"$max": [0, {"$add": [{"$ifNull": ["$count", 0]}, delta]}]},
                        "completed": {"$ifNull": ["$completed", False]},
                        "completedAt": {"$ifNull": ["$completedAt", None]},
                        "notes": {"$ifNull": ["$notes", {"$literal": ""}]},
                        "createdAt": {"$ifNull": ["$createdAt", moment]},
                        "updatedAt": moment,
                    }
                }
            ],
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return int((doc or {}).get("count", 0))

    async def reset_wellness_count(
        self, user_id: str | ObjectId, day: str, moment: datetime
    ) -> None:
        await self._col.update_one(
            self._wellness_key(user_id, day),
            {
                "$set": {"count": 0, "updatedAt": moment},
                "$setOnInsert": {
                    "createdAt": moment,
                    "completed": False,
                    "completedAt": None,
                    "notes": "",
                },
            },
            upsert=True,
        )

    async def set_wellness_notes(
        self, user_id: str | ObjectId, day: str, notes: str, moment: datetime
    ) -> None:
        await self._col.update_one(
            self._wellness_key(user_id, day),
            {
                "$set": {"notes": notes, "updatedAt": moment},
                "$setOnInsert": {
                    "createdAt": moment,
                    "completed": False,
                    "completedAt": None,
                    "count": 0,
                },
            },
            upsert=True,
        )
