"""Collection indexes. Mirrors the Mongoose schemas so both apps can share one database."""

import logging

from pymongo import ASCENDING
from pymongo.asynchronous.database import AsyncDatabase

logger = logging.getLogger(__name__)

_THREE_DAYS = 3 * 24 * 60 * 60


async def ensure_indexes(db: AsyncDatabase) -> None:
    await db.users.create_index([("email", ASCENDING)], unique=True)

    await db.otps.create_index([("email", ASCENDING), ("purpose", ASCENDING)], unique=True)
    await db.otps.create_index([("expiresAt", ASCENDING)], expireAfterSeconds=0)

    await db.sessions.create_index([("tokenHash", ASCENDING)], unique=True)
    await db.sessions.create_index([("userId", ASCENDING)])
    await db.sessions.create_index([("expiresAt", ASCENDING)], expireAfterSeconds=0)

    await db.medications.create_index([("userId", ASCENDING)])
    await db.medications.create_index([("userId", ASCENDING), ("name", ASCENDING)], unique=True)

    await db.dailylogs.create_index([("userId", ASCENDING)])
    await db.dailylogs.create_index([("date", ASCENDING)])
    await db.dailylogs.create_index(
        [
            ("userId", ASCENDING),
            ("date", ASCENDING),
            ("medicationName", ASCENDING),
            ("scheduledTime", ASCENDING),
        ],
        unique=True,
    )

    await db.pushtokens.create_index([("token", ASCENDING)], unique=True)
    await db.pushtokens.create_index([("userId", ASCENDING)])
    await db.pushtokens.create_index([("sessionId", ASCENDING)])

    await db.remindersents.create_index(
        [
            ("userId", ASCENDING),
            ("date", ASCENDING),
            ("medicationName", ASCENDING),
            ("scheduledTime", ASCENDING),
        ],
        unique=True,
    )
    await db.remindersents.create_index([("createdAt", ASCENDING)], expireAfterSeconds=_THREE_DAYS)
    logger.info("MongoDB indexes verified")
