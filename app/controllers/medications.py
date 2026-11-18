from typing import Annotated

from fastapi import APIRouter, Path, status

from app.dependencies import CurrentUser, MedicationServiceDep
from app.schemas.common import OkResponse
from app.schemas.medication import (
    MedicationEnabledInput,
    MedicationInput,
    MedicationsPageData,
    MedicationView,
)

router = APIRouter(prefix="/medications", tags=["medications"])

MedicationId = Annotated[str, Path(pattern=r"^[0-9a-fA-F]{24}$", description="Medication id")]


@router.get(
    "", response_model=MedicationsPageData, summary="Medications with today's doses and history"
)
async def list_medications(user: CurrentUser, service: MedicationServiceDep) -> MedicationsPageData:
    return await service.page_data(user.id)


@router.post(
    "",
    response_model=MedicationView,
    status_code=status.HTTP_201_CREATED,
    summary="Create a medication",
)
async def create_medication(
    body: MedicationInput, user: CurrentUser, service: MedicationServiceDep
) -> MedicationView:
    return await service.create(user.id, body)


@router.put("/{medication_id}", response_model=MedicationView, summary="Update a medication")
async def update_medication(
    medication_id: MedicationId,
    body: MedicationInput,
    user: CurrentUser,
    service: MedicationServiceDep,
) -> MedicationView:
    return await service.update(user.id, medication_id, body)


@router.patch(
    "/{medication_id}/enabled",
    response_model=MedicationView,
    summary="Enable or disable a medication",
)
async def set_medication_enabled(
    medication_id: MedicationId,
    body: MedicationEnabledInput,
    user: CurrentUser,
    service: MedicationServiceDep,
) -> MedicationView:
    return await service.set_enabled(user.id, medication_id, body.enabled)


@router.delete("/{medication_id}", response_model=OkResponse, summary="Delete a medication")
async def delete_medication(
    medication_id: MedicationId, user: CurrentUser, service: MedicationServiceDep
) -> OkResponse:
    await service.delete(user.id, medication_id)
    return OkResponse()
