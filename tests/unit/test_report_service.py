"""The 7-day adherence report: numbers, PDF output and the email send."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.core.exceptions import BadGatewayError, BadRequestError, TooManyRequestsError
from app.services.report_pdf import render_pdf
from app.services.report_render import render_html, render_text
from app.services.report_service import ReportService
from app.services.schedule_service import ScheduleService
from app.services.statistics_service import StatisticsService
from tests.fakes import FakeDailyLogs, FakeEmail, FakeMedications, med_doc

# Wednesday 2026-01-07, 10:00 IST (04:30 UTC). The last 7 days are Jan 1 - Jan 7.
NOW = datetime(2026, 1, 7, 4, 30, tzinfo=UTC)
USER = "u1"


def run(coro):
    return asyncio.run(coro)


class Setup:
    def __init__(self, email: FakeEmail | None = None) -> None:
        self.meds = FakeMedications(
            [
                med_doc(USER, "Biotin", ["8:00 AM", "8:00 PM"]),
                med_doc(USER, "Minoxidil <b>", ["10:00 AM"], days=[1, 3, 5]),  # Mon/Wed/Fri
                med_doc(USER, "Paused", ["7:00 AM"], enabled=False),
            ]
        )
        self.logs = FakeDailyLogs()
        self.email = email or FakeEmail()
        self.cooldowns: dict[str, datetime] = {}
        self.service = ReportService(
            self.logs,
            ScheduleService(self.meds, self.logs),
            StatisticsService(self.logs, ScheduleService(self.meds, self.logs)),
            self.email,
            "Medication Tracker",
            self.cooldowns,
        )

    def build(self, now: datetime = NOW):
        return run(self.service.build(USER, "last7", now))


def test_report_covers_seven_days_and_counts_only_due_doses():
    s = Setup()
    report = s.build()

    assert (report.start_date, report.end_date) == ("2026-01-01", "2026-01-07")
    assert [d.date for d in report.days][0] == "2026-01-01"
    assert len(report.days) == 7

    today = report.days[-1]  # Wed 10:00: Biotin 8 AM is due; 10 AM Minoxidil and 8 PM are not yet
    assert (today.total, today.taken, today.missed) == (1, 0, ("Biotin (8:00 AM)",))

    # Jan 1 is a Thursday: only Biotin (2 doses); Minoxidil isn't due. The paused one never counts.
    assert report.days[0].weekday == "Thu"
    assert report.days[0].total == 2
    assert all("Paused" not in m for d in report.days for m in d.missed)


def test_report_counts_taken_doses_and_percentages():
    s = Setup()
    for date in ("2026-01-01", "2026-01-03"):  # Thu and Sat: Minoxidil isn't due
        s.logs.add_dose(USER, date, "Biotin", "8:00 AM", completed_at=NOW)
        s.logs.add_dose(USER, date, "Biotin", "8:00 PM", completed_at=NOW)
    s.logs.add_dose(USER, "2026-01-07", "Biotin", "8:00 AM", completed_at=NOW)

    report = s.build()
    assert [d.taken == d.total for d in (report.days[0], report.days[2])] == [True, True]
    assert report.days[-1].taken == 1 and report.days[-1].missed == ()
    assert report.taken == 5 and report.perfect_days == 3
    assert report.total == report.taken + report.missed_count
    biotin = next(m for m in report.medications if m.name == "Biotin")
    assert biotin.taken == 5


def test_report_needs_a_medication():
    s = Setup()
    s.meds.docs.clear()
    with pytest.raises(BadRequestError, match="Add a medication"):
        s.build()


def test_pdf_and_html_render_for_any_medication_name():
    report = Setup().build()
    pdf = render_pdf(report, "Medication Tracker", "me@example.com")
    assert pdf.startswith(b"%PDF") and len(pdf) > 1500

    html = render_html(report, "Medication Tracker", "me@example.com")
    assert "&lt;b&gt;" in html and "<b>)" not in html  # names are escaped
    text = render_text(report, "Medication Tracker", "me@example.com")
    assert "Jan 1 – Jan 7, 2026" in text


def test_send_emails_the_report_with_the_pdf_attached():
    s = Setup()
    result = run(s.service.send(USER, "me@example.com", "last7", NOW))

    assert (result.email, result.start_date, result.end_date) == (
        "me@example.com",
        "2026-01-01",
        "2026-01-07",
    )
    to, subject, html, _text, attachment = s.email.reports[0]
    assert to == "me@example.com" and "Jan 1" in subject and "Adherence" in html
    assert attachment is not None
    name, content = attachment
    assert name == "medication-report-2026-01-01_to_2026-01-07.pdf"
    assert content.startswith(b"%PDF")


def test_send_has_a_cooldown_and_a_failed_send_does_not_start_it():
    s = Setup(FakeEmail(fail=True))
    with pytest.raises(BadGatewayError):
        run(s.service.send(USER, "me@example.com", "last7", NOW))

    s.email.fail = False
    run(s.service.send(USER, "me@example.com", "last7", NOW))
    with pytest.raises(TooManyRequestsError):
        run(s.service.send(USER, "me@example.com", "last7", NOW + timedelta(seconds=10)))
    run(s.service.send(USER, "me@example.com", "last7", NOW + timedelta(minutes=2)))
    assert len(s.email.reports) == 2


def test_html_email_uses_the_statistics_page_thresholds():
    from app.services.report_render import _tone

    green, amber, rose = "#16a34a", "#d97706", "#dc2626"
    assert [_tone(v) for v in (100, 80, 79, 50, 49, 0)] == [green, green, amber, amber, rose, rose]
