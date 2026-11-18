from fastapi import APIRouter

from app.core.exceptions import ServiceUnavailableError
from app.db import mongo

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", summary="Readiness probe (checks MongoDB)")
async def ready() -> dict[str, str]:
    try:
        await mongo.ping()
    except Exception as exc:
        raise ServiceUnavailableError("Database is unreachable.") from exc
    return {"status": "ok"}
