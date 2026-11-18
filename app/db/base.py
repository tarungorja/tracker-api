from datetime import datetime
from typing import Any

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.utils.time import utcnow

__all__ = ["DuplicateKeyError", "as_object_id", "created_stamps", "now", "updated_stamp"]


def as_object_id(value: str | ObjectId) -> ObjectId:
    return value if isinstance(value, ObjectId) else ObjectId(value)


def now() -> datetime:
    return utcnow()


def created_stamps(moment: datetime) -> dict[str, Any]:
    """Mongoose-style timestamps for newly inserted documents."""
    return {"createdAt": moment, "updatedAt": moment}


def updated_stamp(moment: datetime) -> dict[str, Any]:
    return {"updatedAt": moment}
