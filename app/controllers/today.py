from fastapi import APIRouter

from app.dependencies import CurrentUser, TodayServiceDep
from app.schemas.today import TodayData

router = APIRouter(prefix="/today", tags=["today"])


@router.get("", response_model=TodayData, summary="Today's dose timeline")
async def get_today(user: CurrentUser, service: TodayServiceDep) -> TodayData:
    return await service.get(user.id)
