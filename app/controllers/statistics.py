from fastapi import APIRouter

from app.dependencies import CurrentUser, StatisticsServiceDep
from app.schemas.statistics import StatisticsData

router = APIRouter(prefix="/statistics", tags=["statistics"])


@router.get("", response_model=StatisticsData, summary="Adherence statistics and heatmap")
async def get_statistics(user: CurrentUser, service: StatisticsServiceDep) -> StatisticsData:
    return await service.get(user.id)
