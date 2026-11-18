from collections.abc import Iterable
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.db.base import as_object_id, now


class PushTokenRepository:
    def __init__(self, db: AsyncDatabase) -> None:
        self._col = db.pushtokens

    async def upsert(
        self,
        token: str,
        user_id: str | ObjectId,
        session_id: str | ObjectId,
        user_agent: str,
    ) -> None:
        """A token belongs to one user/session at a time; re-registering reassigns it."""
        moment = now()
        await self._col.update_one(
            {"token": token},
            {
                "$set": {
                    "userId": as_object_id(user_id),
                    "sessionId": as_object_id(session_id),
                    "userAgent": user_agent,
                    "updatedAt": moment,
                },
                "$setOnInsert": {"createdAt": moment},
            },
            upsert=True,
        )

    async def delete_for_user(self, token: str, user_id: str | ObjectId) -> None:
        await self._col.delete_one({"token": token, "userId": as_object_id(user_id)})

    async def delete_by_session(self, session_id: ObjectId) -> None:
        await self._col.delete_many({"sessionId": session_id})

    async def delete_by_tokens(self, tokens: Iterable[str]) -> None:
        await self._col.delete_many({"token": {"$in": list(tokens)}})

    async def distinct_user_ids(self) -> list[ObjectId]:
        return await self._col.distinct("userId")

    async def delete_orphaned(
        self, user_id: str | ObjectId, active_session_ids: list[ObjectId]
    ) -> None:
        """Drops tokens whose login session has ended (expired without signing out)."""
        await self._col.delete_many(
            {
                "userId": as_object_id(user_id),
                "sessionId": {"$exists": True, "$nin": active_session_ids},
            }
        )

    async def tokens_for_user(
        self, user_id: str | ObjectId, active_session_ids: list[ObjectId]
    ) -> list[str]:
        """Tokens for live sessions, plus legacy tokens saved before sessions were tracked."""
        docs: list[dict[str, Any]] = await self._col.find(
            {
                "userId": as_object_id(user_id),
                "$or": [
                    {"sessionId": {"$in": active_session_ids}},
                    {"sessionId": {"$exists": False}},
                ],
            },
            {"token": 1},
        ).to_list(None)
        return list(dict.fromkeys(d["token"] for d in docs))
