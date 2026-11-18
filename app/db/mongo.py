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
    if _database is None:
        raise RuntimeError("Database is not connected. Call connect() on startup.")
    return _database


async def ping() -> None:
    await get_database().command("ping")
