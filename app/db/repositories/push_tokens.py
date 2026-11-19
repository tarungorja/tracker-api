from collections.abc import Iterable
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.db.base import as_object_id, now

# The Android app sends this user agent (prefix) when it registers its FCM token.
NATIVE_USER_AGENT_PREFIX = "HairHealthTracker-Android"
_NOT_NATIVE: dict[str, Any] = {"userAgent": {"$not": {"$regex": f"^{NATIVE_USER_AGENT_PREFIX}"}}}


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

    async def delete_by_session(self, session_id: str | ObjectId) -> None:
        await self._col.delete_many({"sessionId": as_object_id(session_id)})

    async def delete_by_tokens(self, tokens: Iterable[str]) -> None:
        await self._col.delete_many({"token": {"$in": list(tokens)}})

    async def distinct_user_ids(self, include_native: bool = True) -> list[ObjectId]:
        """Users with a registered device; `include_native=False` ignores the Android app."""
        return await self._col.distinct("userId", {} if include_native else _NOT_NATIVE)

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
        self,
        user_id: str | ObjectId,
        active_session_ids: list[ObjectId],
        include_native: bool = True,
    ) -> list[str]:
        """Tokens for live sessions, plus legacy tokens saved before sessions were tracked.

        `include_native=False` leaves out the Android app's tokens (userAgent missing counts as
        not native).
        """
        query: dict[str, Any] = {
            "userId": as_object_id(user_id),
            "$or": [
                {"sessionId": {"$in": active_session_ids}},
                {"sessionId": {"$exists": False}},
            ],
        }
        if not include_native:
            query.update(_NOT_NATIVE)
        docs: list[dict[str, Any]] = await self._col.find(query, {"token": 1}).to_list(None)
        return list(dict.fromkeys(d["token"] for d in docs))

    async def delete_all_for_user(self, user_id: str | ObjectId) -> int:
        result = await self._col.delete_many({"userId": as_object_id(user_id)})
        return result.deleted_count
