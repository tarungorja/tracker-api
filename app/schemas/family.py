from pydantic import Field

from app.schemas.common import CamelModel, OkResponse
from app.schemas.dashboard import DashboardData
from app.schemas.dose import DoseView


class InviteView(CamelModel):
    code: str
    """Shown once, formatted for reading aloud, e.g. "K7QM-2XPD"."""
    expires_at: str


class ConnectInput(CamelModel):
    code: str = Field(min_length=1, max_length=40)


class LinkedUser(CamelModel):
    id: str
    email: str
    linked_at: str


class MedicationActivityView(CamelModel):
    action: str
    """added | updated | removed | enabled | disabled"""
    medication_name: str
    at: str


class PatientOverview(CamelModel):
    patient: LinkedUser
    dashboard: DashboardData
    missed: list[DoseView]
    """Today's doses whose time has passed and that aren't marked as taken."""
    activity: list[MedicationActivityView]
    last_medication_update_at: str | None
    last_dose_logged_at: str | None
    last_reminded_at: str | None
    remind_available_in_seconds: int


class RemindResult(OkResponse):
    sent: int
    missed_count: int
