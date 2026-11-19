import logging

from app.core.exceptions import NotFoundError
from app.db.repositories import (
    CaregiverLinkRepository,
    DailyLogRepository,
    InviteCodeRepository,
    MedicationActivityRepository,
    MedicationRepository,
    OtpRepository,
    PushTokenRepository,
    ReminderSentRepository,
    SessionRepository,
    UserRepository,
)

logger = logging.getLogger(__name__)


class AccountService:
    """Permanent account deletion (the user's right to erasure)."""

    def __init__(
        self,
        users: UserRepository,
        sessions: SessionRepository,
        otps: OtpRepository,
        push_tokens: PushTokenRepository,
        medications: MedicationRepository,
        daily_logs: DailyLogRepository,
        reminders_sent: ReminderSentRepository,
        caregiver_links: CaregiverLinkRepository,
        invite_codes: InviteCodeRepository,
        medication_activity: MedicationActivityRepository,
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._otps = otps
        self._push_tokens = push_tokens
        self._medications = medications
        self._daily_logs = daily_logs
        self._reminders_sent = reminders_sent
        self._caregiver_links = caregiver_links
        self._invite_codes = invite_codes
        self._medication_activity = medication_activity

    async def delete_account(self, user_id: str, email: str) -> None:
        """Removes the user and everything they own.

        Health data goes first and the user record last-but-one, so a failure part-way leaves the
        user still able to sign in and simply retry. Every step is idempotent.
        """
        await self._medications.delete_all_for_user(user_id)
        await self._daily_logs.delete_all_for_user(user_id)  # dose logs, wellness counts, notes
        await self._reminders_sent.delete_all_for_user(user_id)
        await self._medication_activity.delete_all_for_user(user_id)
        await self._invite_codes.delete_all_for_user(user_id)
        await self._caregiver_links.delete_all_for_user(user_id)  # as follower and as followed
        await self._push_tokens.delete_all_for_user(user_id)
        await self._otps.delete_for_email(email)
        if not await self._users.delete(user_id):
            raise NotFoundError("Account not found.")
        await self._sessions.delete_all_for_user(user_id)  # signs out every device
        logger.info("Deleted account %s", user_id)
