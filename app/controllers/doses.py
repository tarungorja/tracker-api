from fastapi import APIRouter

from app.dependencies import CurrentUser, DoseServiceDep
from app.schemas.common import OkResponse
from app.schemas.dose import DoseCompletionInput

router = APIRouter(prefix="/doses", tags=["doses"])


@router.put("/completion", response_model=OkResponse, summary="Mark a dose taken / not taken")
async def set_dose_completion(
    body: DoseCompletionInput, user: CurrentUser, service: DoseServiceDep
) -> OkResponse:
    await service.set_completion(user.id, body)
    return OkResponse()
