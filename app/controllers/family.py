from typing import Annotated

from fastapi import APIRouter, Path

from app.dependencies import CurrentUser, FamilyServiceDep
from app.schemas.common import OkResponse
from app.schemas.family import (
    ConnectInput,
    InviteView,
    LinkedUser,
    PatientOverview,
    RemindResult,
)

router = APIRouter(prefix="/family", tags=["family"])

UserIdPath = Annotated[str, Path(pattern=r"^[0-9a-fA-F]{24}$")]


@router.post("/invite", response_model=InviteView, summary="Create a one-time invite code")
async def create_invite(user: CurrentUser, service: FamilyServiceDep) -> InviteView:
    return await service.create_invite(user.id)


@router.post("/connect", response_model=LinkedUser, summary="Connect to an account using its code")
async def connect(body: ConnectInput, user: CurrentUser, service: FamilyServiceDep) -> LinkedUser:
    return await service.connect(user.id, body.code)


@router.get("/patients", response_model=list[LinkedUser], summary="Accounts I follow")
async def list_patients(user: CurrentUser, service: FamilyServiceDep) -> list[LinkedUser]:
    return await service.list_patients(user.id)


@router.get("/caregivers", response_model=list[LinkedUser], summary="People who follow my account")
async def list_caregivers(user: CurrentUser, service: FamilyServiceDep) -> list[LinkedUser]:
    return await service.list_caregivers(user.id)


@router.delete("/patients/{patient_id}", response_model=OkResponse, summary="Stop following")
async def stop_following(
    patient_id: UserIdPath, user: CurrentUser, service: FamilyServiceDep
) -> OkResponse:
    await service.stop_following(user.id, patient_id)
    return OkResponse()


@router.delete(
    "/caregivers/{caregiver_id}", response_model=OkResponse, summary="Revoke someone's access"
)
async def revoke_caregiver(
    caregiver_id: UserIdPath, user: CurrentUser, service: FamilyServiceDep
) -> OkResponse:
    await service.revoke_caregiver(user.id, caregiver_id)
    return OkResponse()


@router.get(
    "/patients/{patient_id}/overview",
    response_model=PatientOverview,
    summary="Read-only dashboard of a followed account",
)
async def patient_overview(
    patient_id: UserIdPath, user: CurrentUser, service: FamilyServiceDep
) -> PatientOverview:
    return await service.overview(user.id, patient_id)


@router.post(
    "/patients/{patient_id}/remind",
    response_model=RemindResult,
    summary="Push a missed-dose reminder (only when a dose was missed)",
)
async def remind_patient(
    patient_id: UserIdPath, user: CurrentUser, service: FamilyServiceDep
) -> RemindResult:
    return await service.remind(user.id, user.email, patient_id)
