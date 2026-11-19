"""Adherence reports: built from the schedule and dose logs, emailed or downloaded as a PDF."""

from datetime import datetime

from app.core.constants import REPORT_SEND_COOLDOWN, WEEKDAY_SHORT
from app.core.exceptions import BadGatewayError, BadRequestError, TooManyRequestsError
from app.db.repositories import DailyLogRepository
from app.integrations.email import BrevoEmailClient, EmailDeliveryError
from app.schemas.report import ReportPeriod, ReportSendResult
from app.services.report_pdf import render_pdf
from app.services.report_render import (
    DayReport,
    MedicationReport,
    Report,
    render_html,
    render_text,
    report_filename,
    report_subject,
)
from app.services.schedule_service import ScheduleService
from app.utils.schedule import is_medication_due_on
from app.utils.time import (
    add_days_to_key,
    date_key_range,
    now_context,
    parse_schedule_to_minutes,
    utcnow,
    weekday_of_key,
)

# Last time each user emailed a report. Shared across requests (services are built per request).
_last_emailed: dict[str, datetime] = {}


def resolve_period(period: ReportPeriod, today_key: str) -> tuple[str, str]:
    """(start, end) date keys, inclusive. "custom" will be added here later."""
    if period == "last7":
        return add_days_to_key(today_key, -6), today_key
    raise BadRequestError("Unsupported report period.")


class ReportService:
    def __init__(
        self,
        logs: DailyLogRepository,
        schedule: ScheduleService,
        email: BrevoEmailClient,
        app_name: str,
        last_emailed: dict[str, datetime] | None = None,
    ) -> None:
        self._logs = logs
        self._schedule = schedule
        self._email = email
        self._app_name = app_name
        self._last_emailed = _last_emailed if last_emailed is None else last_emailed

    async def build(
        self, user_id: str, period: ReportPeriod, now: datetime | None = None
    ) -> Report:
        today_key, now_minutes = now_context(now or utcnow())
        start_key, end_key = resolve_period(period, today_key)

        meds = await self._schedule.medication_views(user_id, only_enabled=True)
        if not meds:
            raise BadRequestError("Add a medication first: there's nothing to report on yet.")
        rows = await self._logs.find_doses_in_range(user_id, start_key, end_key)
        taken_keys = {
            (r["date"], r["medicationName"], r["scheduledTime"]) for r in rows if r.get("completed")
        }

        per_med = {m.name: [0, 0] for m in meds}  # name -> [total, taken]
        days: list[DayReport] = []
        for key in date_key_range(start_key, end_key):
            total = taken = 0
            missed: list[str] = []
            for med in meds:
                if not is_medication_due_on(med.days_of_week, key):
                    continue
                for time in med.schedule_times:
                    # Doses later today haven't been missed yet, so they don't count.
                    if key == today_key and (parse_schedule_to_minutes(time) or 0) >= now_minutes:
                        continue
                    total += 1
                    per_med[med.name][0] += 1
                    if (key, med.name, time) in taken_keys:
                        taken += 1
                        per_med[med.name][1] += 1
                    else:
                        missed.append(f"{med.name} ({time})")
            days.append(
                DayReport(
                    date=key,
                    weekday=WEEKDAY_SHORT[weekday_of_key(key)],
                    total=total,
                    taken=taken,
                    missed=tuple(missed),
                )
            )

        medications = tuple(
            MedicationReport(name=name, total=total, taken=taken)
            for name, (total, taken) in sorted(per_med.items())
            if total > 0
        )
        return Report(start_key, end_key, tuple(days), medications)

    async def render_download(
        self, user_id: str, email: str, period: ReportPeriod, now: datetime | None = None
    ) -> tuple[str, bytes]:
        """(filename, PDF bytes) for the browser to save."""
        report = await self.build(user_id, period, now)
        return report_filename(report), render_pdf(report, self._app_name, email)

    async def send(
        self, user_id: str, email: str, period: ReportPeriod, now: datetime | None = None
    ) -> ReportSendResult:
        moment = now or utcnow()
        last = self._last_emailed.get(user_id)
        if last is not None and moment - last < REPORT_SEND_COOLDOWN:
            raise TooManyRequestsError(
                "A report was just emailed to you. Please wait a minute before sending another."
            )

        report = await self.build(user_id, period, moment)
        self._last_emailed[user_id] = moment
        try:
            await self._email.send_report(
                email,
                report_subject(report, self._app_name),
                render_html(report, self._app_name, email),
                render_text(report, self._app_name, email),
                attachment=(report_filename(report), render_pdf(report, self._app_name, email)),
            )
        except EmailDeliveryError as exc:
            self._last_emailed.pop(user_id, None)  # nothing was sent, let them retry
            raise BadGatewayError(str(exc)) from exc
        return ReportSendResult(email=email, start_date=report.start_date, end_date=report.end_date)
