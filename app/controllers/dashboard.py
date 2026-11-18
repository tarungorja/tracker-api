from fastapi import APIRouter

from app.dependencies import CurrentUser, DashboardServiceDep
from app.schemas.dashboard import DashboardData

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardData, summary="Home dashboard data")
async def get_dashboard(user: CurrentUser, service: DashboardServiceDep) -> DashboardData:
    return await service.get(user.id)
