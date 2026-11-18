"""One-off migration for per-user data (ported from the Next.js app's migrate-user-scope.ts).

Drops the old globally-unique indexes (they would block a second user's data) and builds the
current ones. Run once per database:

    .venv\\Scripts\\python -m scripts.migrate_user_scope
"""

import asyncio

from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import OperationFailure

from app.core.config import get_settings
from app.db import mongo
from app.db.indexes import ensure_indexes

OBSOLETE_INDEXES = [
    ("medications", "name_1"),
    ("dailylogs", "date_1_medicationName_1_scheduledTime_1"),
]


async def drop_index_if_exists(db: AsyncDatabase, collection: str, name: str) -> None:
    try:
        await db[collection].drop_index(name)
        print(f"Dropped index {collection}.{name}")
    except OperationFailure as exc:
        if exc.code in (27, 26):  # IndexNotFound, NamespaceNotFound
            print(f"Index {collection}.{name} not present, skipping")
            return
        raise


async def main() -> None:
    mongo.connect(get_settings())
    try:
        db = mongo.get_database()
        for collection, name in OBSOLETE_INDEXES:
            await drop_index_if_exists(db, collection, name)
        await ensure_indexes(db)
        print("Indexes are up to date.")
    finally:
        await mongo.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
