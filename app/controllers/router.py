from fastapi import APIRouter

from app.controllers import (
    auth,
    cron,
    dashboard,
    doses,
    family,
    medications,
    push,
    reports,
    statistics,
    today,
    wellness,
)

api_router = APIRouter()
for module in (
    auth,
    dashboard,
    today,
    medications,
    doses,
    statistics,
    wellness,
    family,
    reports,
    push,
    cron,
):
    api_router.include_router(module.router)
