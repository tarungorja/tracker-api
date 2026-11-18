import asyncio

from app.db import mongo


def test_database_connects_lazily_when_startup_hook_did_not_run():
    asyncio.run(mongo.disconnect())  # make sure we start disconnected
    try:
        db = mongo.get_database()  # no connect() call: must not raise
        assert db.name == "health_test"  # from MONGODB_URI in tests/conftest.py
        assert mongo.get_database() is db  # reused afterwards
    finally:
        asyncio.run(mongo.disconnect())
