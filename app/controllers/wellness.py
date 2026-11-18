from typing import Annotated

from fastapi import APIRouter, Query

from app.dependencies import CurrentUser, WellnessServiceDep
from app.schemas.common import CountResult, DateKey, OkResponse
from app.schemas.wellness import NotesInput, WellnessData

router = APIRouter(prefix="/wellness", tags=["wellness"])

DateQuery = Annotated[DateKey | None, Query(description="YYYY-MM-DD (IST). Defaults to today.")]


@router.get("", response_model=WellnessData, summary="Wellness counters, charts and history")
async def get_wellness(user: CurrentUser, service: WellnessServiceDep) -> WellnessData:
    return await service.get(user.id)


@router.post("/count/increment", response_model=CountResult, summary="Add one to the day's count")
async def increment_count(
    user: CurrentUser, service: WellnessServiceDep, date: DateQuery = None
) -> CountResult:
    return CountResult(count=await service.increment(user.id, date))


@router.post("/count/decrement", response_model=CountResult, summary="Subtract one (min 0)")
async def decrement_count(
    user: CurrentUser, service: WellnessServiceDep, date: DateQuery = None
) -> CountResult:
    return CountResult(count=await service.decrement(user.id, date))


@router.post("/count/reset", response_model=CountResult, summary="Reset the day's count to 0")
async def reset_count(
    user: CurrentUser, service: WellnessServiceDep, date: DateQuery = None
) -> CountResult:
    return CountResult(count=await service.reset(user.id, date))


@router.put("/notes", response_model=OkResponse, summary="Save the day's note")
async def set_notes(body: NotesInput, user: CurrentUser, service: WellnessServiceDep) -> OkResponse:
    await service.set_notes(user.id, body.notes, body.date)
    return OkResponse()
