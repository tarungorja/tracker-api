import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.constants import REMINDER_LOOKBACK_MINUTES
from app.db.repositories import (
    DailyLogRepository,
    MedicationRepository,
    PushTokenRepository,
    ReminderSentRepository,
)
from app.schemas.push import ReminderRunResult
from app.services.push_service import PushPayload, PushService
from app.utils.time import (
    ALL_DAYS,
    ist_date_key,
    ist_minutes_of_day,
    minutes_to_label,
    parse_schedule_to_minutes,
    utcnow,
    weekday_of_key,
)

logger = logging.getLogger(__name__)


@dataclass
class _Slot:
    date_key: str
    time: str
    names: list[str]


def _recent_moments(now: datetime) -> list[tuple[str, int]]:
    """Distinct (IST date, minute-of-day) pairs covering the lookback window."""
    moments = []
    for k in range(REMINDER_LOOKBACK_MINUTES):
        t = now - timedelta(minutes=k)
        moments.append((ist_date_key(t), ist_minutes_of_day(t)))
    return moments


class ReminderService:
    """Sends due dose reminders. Meant to be triggered every minute by an external scheduler.

    External crons are rarely exact, so a dose still counts as due for a few minutes after its
    scheduled minute. The ReminderSent unique index prevents duplicate notifications.
    """

    def __init__(
        self,
        push_tokens: PushTokenRepository,
        medications: MedicationRepository,
        logs: DailyLogRepository,
        reminders_sent: ReminderSentRepository,
        push: PushService,
    ) -> None:
        self._push_tokens = push_tokens
        self._medications = medications
        self._logs = logs
        self._reminders_sent = reminders_sent
        self._push = push

    async def send_due(self, now: datetime | None = None) -> ReminderRunResult:
        now = now or utcnow()
        user_ids = await self._push_tokens.distinct_user_ids()
        result = ReminderRunResult(
            users_checked=len(user_ids), doses_due=0, notifications_sent=0, failures=0
        )
        if not user_ids:
            return result

        meds = await self._medications.list_enabled_for_users(user_ids)
        moments = _recent_moments(now)

        # user id -> "date|time" -> slot of medication names newly claimed in this run
        to_notify: dict[str, dict[str, _Slot]] = {}

        for med in meds:
            user_id = str(med["userId"])
            for label in med.get("scheduleTimes", []):
                minutes = parse_schedule_to_minutes(label)
                if minutes is None:
                    continue
                for date_key, moment_minutes in moments:
                    if moment_minutes != minutes:
                        continue
                    # Medications saved before weekday support have no days: every day.
                    days = med.get("daysOfWeek") or ALL_DAYS
                    if weekday_of_key(date_key) not in days:
                        continue
                    result.doses_due += 1

                    time = minutes_to_label(minutes)
                    if await self._logs.is_dose_completed(user_id, date_key, med["name"], time):
                        continue
                    if not await self._reminders_sent.claim(user_id, date_key, med["name"], time):
                        continue

                    slot = to_notify.setdefault(user_id, {}).setdefault(
                        f"{date_key}|{time}", _Slot(date_key, time, [])
                    )
                    slot.names.append(med["name"])

        for user_id, slots in to_notify.items():
            for slot in slots.values():
                delivered = False
                try:
                    sent = await self._push.send_to_user(
                        user_id,
                        PushPayload(
                            title=f"Time for your {slot.time} medication",
                            body=", ".join(slot.names),
                            tag=f"dose-{slot.date_key}-{slot.time}",
                        ),
                    )
                    result.notifications_sent += sent.sent
                    result.failures += sent.failed
                    # No registered device at all (tokens pruned) means nothing to retry.
                    delivered = sent.sent > 0 or sent.failed == 0
                except Exception:
                    logger.exception("Reminder push failed for user %s", user_id)
                    result.failures += 1

                if not delivered:
                    # Release the claim so the next run inside the lookback window retries.
                    await self._reminders_sent.release(
                        user_id, slot.date_key, slot.time, slot.names
                    )

        return result
