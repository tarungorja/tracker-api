"""Family sharing: a patient (father) invites a caregiver (son) who follows along read-only."""

import logging
import math
from datetime import UTC, datetime
from typing import Any

from app.core.constants import (
    ACTIVITY_LIMIT,
    CAREGIVER_REMIND_COOLDOWN,
    INVITE_CODE_LENGTH,
    INVITE_CODE_TTL,
)
from app.core.exceptions import (
    BadGatewayError,
    BadRequestError,
    ConflictError,
    NotFoundError,
    TooManyRequestsError,
)
from app.core.security import generate_invite_code, hash_token, normalize_invite_code
from app.db.repositories import (
    CaregiverLinkRepository,
    InviteCodeRepository,
    MedicationActivityRepository,
    UserRepository,
)
from app.schemas.dose import DoseView
from app.schemas.family import (
    InviteView,
    LinkedUser,
    MedicationActivityView,
    PatientOverview,
    RemindResult,
)
from app.services.dashboard_service import DashboardService
from app.services.push_service import PushPayload, PushService
from app.utils.time import to_iso_z, utcnow

logger = logging.getLogger(__name__)

_NOT_LINKED = "You're not connected to this account."
_BAD_CODE = "That code isn't valid or has expired. Ask for a new one."


def missed_doses(doses: list[DoseView], now_minutes: int) -> list[DoseView]:
    """Today's doses that are past their time and still not marked as taken."""
    return [d for d in doses if not d.completed and d.scheduled_minutes < now_minutes]


def format_invite_code(code: str) -> str:
    half = INVITE_CODE_LENGTH // 2
    return f"{code[:half]}-{code[half:]}"


def _iso(moment: datetime | None) -> str | None:
    return to_iso_z(moment) if moment else None


class FamilyService:
    def __init__(
        self,
        users: UserRepository,
        links: CaregiverLinkRepository,
        invites: InviteCodeRepository,
        activity: MedicationActivityRepository,
        dashboard: DashboardService,
        push: PushService,
    ) -> None:
        self._users = users
        self._links = links
        self._invites = invites
        self._activity = activity
        self._dashboard = dashboard
        self._push = push

    # ---- linking -------------------------------------------------------------------------

    async def create_invite(self, patient_id: str, now: datetime | None = None) -> InviteView:
        """Issues a fresh single-use code (replacing any earlier one)."""
        moment = now or utcnow()
        code = generate_invite_code()
        expires_at = moment + INVITE_CODE_TTL
        await self._invites.replace_for_patient(patient_id, hash_token(code), expires_at)
        return InviteView(code=format_invite_code(code), expires_at=to_iso_z(expires_at))

    async def connect(self, caregiver_id: str, raw_code: str) -> LinkedUser:
        code = normalize_invite_code(raw_code)
        if len(code) != INVITE_CODE_LENGTH:
            raise BadRequestError(_BAD_CODE)

        invite = await self._invites.consume(hash_token(code))
        if invite is None:
            raise BadRequestError(_BAD_CODE)

        patient_id = str(invite["patientId"])
        if patient_id == str(caregiver_id):
            raise BadRequestError("You can't connect to your own account.")
        patient = await self._users.find_by_id(patient_id)
        if patient is None:
            raise BadRequestError(_BAD_CODE)

        await self._links.create(caregiver_id, patient_id)
        link = await self._links.find(caregiver_id, patient_id)
        return LinkedUser(
            id=patient_id,
            email=patient["email"],
            linked_at=to_iso_z(link["createdAt"]) if link else to_iso_z(utcnow()),
        )

    async def _linked_users(self, links: list[dict[str, Any]], other_key: str) -> list[LinkedUser]:
        if not links:
            return []
        users = await self._users.find_by_ids([link[other_key] for link in links])
        emails = {str(u["_id"]): u["email"] for u in users}
        return [
            LinkedUser(
                id=str(link[other_key]),
                email=emails[str(link[other_key])],
                linked_at=to_iso_z(link["createdAt"]),
            )
            for link in links
            if str(link[other_key]) in emails
        ]

    async def list_patients(self, caregiver_id: str) -> list[LinkedUser]:
        """People I follow."""
        return await self._linked_users(
            await self._links.list_for_caregiver(caregiver_id), "patientId"
        )

    async def list_caregivers(self, patient_id: str) -> list[LinkedUser]:
        """People who follow me."""
        return await self._linked_users(
            await self._links.list_for_patient(patient_id), "caregiverId"
        )

    async def stop_following(self, caregiver_id: str, patient_id: str) -> None:
        if not await self._links.delete(caregiver_id, patient_id):
            raise NotFoundError(_NOT_LINKED)

    async def revoke_caregiver(self, patient_id: str, caregiver_id: str) -> None:
        if not await self._links.delete(caregiver_id, patient_id):
            raise NotFoundError("That person isn't connected to your account.")

    # ---- viewing -------------------------------------------------------------------------

    async def _require_link(self, caregiver_id: str, patient_id: str) -> dict[str, Any]:
        link = await self._links.find(caregiver_id, patient_id)
        if link is None:
            raise NotFoundError(_NOT_LINKED)
        return link

    async def overview(
        self, caregiver_id: str, patient_id: str, now: datetime | None = None
    ) -> PatientOverview:
        link = await self._require_link(caregiver_id, patient_id)
        patient = await self._users.find_by_id(patient_id)
        if patient is None:
            raise NotFoundError(_NOT_LINKED)

        moment = now or utcnow()
        dashboard = await self._dashboard.get(patient_id, moment)
        activity = await self._activity.recent(patient_id, ACTIVITY_LIMIT)

        logged = [d.completed_at for d in dashboard.doses if d.completed_at]
        last_reminded = link.get("lastRemindedAt")
        wait = 0
        if last_reminded:
            ready_at = _as_aware(last_reminded) + CAREGIVER_REMIND_COOLDOWN
            wait = max(0, math.ceil((ready_at - moment).total_seconds()))

        return PatientOverview(
            patient=LinkedUser(
                id=patient_id, email=patient["email"], linked_at=to_iso_z(link["createdAt"])
            ),
            dashboard=dashboard,
            missed=missed_doses(dashboard.doses, dashboard.now_minutes),
            activity=[
                MedicationActivityView(
                    action=a["action"],
                    medication_name=a["medicationName"],
                    at=to_iso_z(a["createdAt"]),
                )
                for a in activity
            ],
            last_medication_update_at=_iso(activity[0]["createdAt"]) if activity else None,
            last_dose_logged_at=max(logged) if logged else None,
            last_reminded_at=_iso(last_reminded),
            remind_available_in_seconds=wait,
        )

    # ---- reminding -----------------------------------------------------------------------

    async def remind(
        self, caregiver_id: str, caregiver_email: str, patient_id: str, now: datetime | None = None
    ) -> RemindResult:
        """Pushes a "you missed a dose" notification to the patient. Only missed doses qualify."""
        await self._require_link(caregiver_id, patient_id)
        # Mongo stores milliseconds; keep the claim marker exactly comparable.
        moment = (now or utcnow()).replace(microsecond=0)

        dashboard = await self._dashboard.get(patient_id, moment)
        missed = missed_doses(dashboard.doses, dashboard.now_minutes)
        if not missed:
            raise ConflictError(
                "Nothing has been missed today, so there's nothing to remind about."
            )

        if not await self._links.claim_reminder(
            caregiver_id, patient_id, moment - CAREGIVER_REMIND_COOLDOWN, moment
        ):
            raise TooManyRequestsError(
                "You reminded them a moment ago. Please wait a few minutes before sending another."
            )

        names = ", ".join(f"{d.medication_name} ({d.scheduled_time})" for d in missed)
        try:
            result = await self._push.send_to_user(
                patient_id,
                PushPayload(
                    title="You missed a dose",
                    body=f"{names}. {caregiver_email} is reminding you to take it.",
                    tag="caregiver-reminder",
                ),
            )
        except Exception as exc:
            await self._links.release_reminder(caregiver_id, patient_id, moment)
            logger.exception("Caregiver reminder failed for patient %s", patient_id)
            raise BadGatewayError(f"Could not send the reminder: {exc}") from exc

        if result.sent == 0:
            await self._links.release_reminder(caregiver_id, patient_id, moment)
            if result.error:
                raise BadGatewayError(f"Firebase could not deliver it: {result.error}")
            raise ConflictError(
                "They haven't turned on notifications on any device yet, so it couldn't be sent."
            )
        return RemindResult(sent=result.sent, missed_count=len(missed))


def _as_aware(moment: datetime) -> datetime:
    """Mongo returns naive UTC datetimes unless the client is tz-aware."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
