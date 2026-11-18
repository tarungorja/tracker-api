from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings

_client: AsyncMongoClient | None = None
_database: AsyncDatabase | None = None


def connect(settings: Settings) -> None:
    """Creates the client. PyMongo connects lazily on first use."""
    global _client, _database
    _client = AsyncMongoClient(
        settings.mongodb_uri,
        tz_aware=True,
        maxPoolSize=10,
        serverSelectionTimeoutMS=10_000,
    )
    _database = (
        _client.get_database(settings.mongodb_db)
        if settings.mongodb_db
        else _client.get_default_database()
    )


async def disconnect() -> None:
    global _client, _database
    if _client is not None:
        await _client.close()
    _client = None
    _database = None


def get_database() -> AsyncDatabase:
    """The shared database handle, connecting on first use.

    Normally connect() runs at startup, but serverless hosts (e.g. Vercel) may not run the
    lifespan hook, so the first request connects lazily instead of failing.
    """
    if _database is None:
        from app.core.config import get_settings

        connect(get_settings())
    assert _database is not None
    return _database


async def ping() -> None:
    await get_database().command("ping")
