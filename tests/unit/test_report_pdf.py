"""PDF content: the 7-day report plus the Statistics page numbers and charts."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from reportlab import rl_config

from app.schemas.dose import DayCompletion
from app.schemas.statistics import MedicationStat, StatisticsData
from app.services.report_pdf import render_pdf
from app.services.report_render import MedicationReport, Report, render_text
from app.utils.time import add_days_to_key, date_key_range
from tests.unit.test_report_service import NOW, USER, Setup

EXISTING = (
    b"Medication adherence report",
    b"me@example.com",
    b"Adherence",
    b"Doses taken",
    b"Doses missed",
    b"Perfect days",
    b"Day by day",
    b"By medication",
    b"Based on current active medications",
    b"Page 1",
)
NEW = (
    b"Statistics overview",
    b"Overall completion",
    b"This month",
    b"CURRENT STREAK",
    b"LONGEST STREAK",
    b"MISSED DOSES",
    b"Daily completion",
    b"Medication completion",
    b"Adherence heatmap",
)


@pytest.fixture
def plain_pdf(monkeypatch):
    """Stops reportlab compressing page streams so the drawn text can be searched."""
    monkeypatch.setattr(rl_config, "pageCompression", 0)


def pdf_of(report: Report) -> bytes:
    pdf = render_pdf(report, "Medication Tracker", "me@example.com")
    assert pdf.startswith(b"%PDF") and pdf.rstrip().endswith(b"%%EOF")
    return pdf


def report_with_data() -> Report:
    s = Setup()
    s.logs.add_dose(USER, "2026-01-01", "Biotin", "8:00 AM", completed_at=NOW)
    return s.build()


def percent_of(done: int, total: int) -> int:
    return round(done / total * 100) if total else 0


def stats_with(
    overall=(0, 0), month=(0, 0), heatmap=(), meds=(), streaks=(0, 0), missed=0
) -> StatisticsData:
    return StatisticsData(
        today_key="2026-01-07",
        overall_percent=percent_of(*overall),
        overall_completed=overall[0],
        overall_total=overall[1],
        month_percent=percent_of(*month),
        month_completed=month[0],
        month_total=month[1],
        current_streak=streaks[0],
        longest_streak=streaks[1],
        missed_reminders=missed,
        heatmap=list(heatmap),
        medication_stats=[
            MedicationStat(name=n, total=t, completed=c, percent=percent_of(c, t))
            for n, c, t in meds
        ],
    )


def heat_days(count: int, end: str = "2026-01-07", ratio=lambda i: (i % 5) / 4):
    keys = date_key_range(add_days_to_key(end, -(count - 1)), end)
    days = []
    for i, key in enumerate(keys):
        done = int(ratio(i) * 4)
        days.append(DayCompletion(date=key, total=4, completed=done, ratio=done / 4))
    return days


def test_pdf_has_every_existing_section_and_the_statistics_sections(plain_pdf):
    pdf = pdf_of(report_with_data())
    for text in EXISTING + NEW:
        assert text in pdf, text.decode()
    assert b"Last 120 days" in pdf and b"Since the 1st" in pdf
    assert b"Less" in pdf and b"More" in pdf  # heatmap legend
    assert b"Minoxidil <" in pdf and b"&lt;" not in pdf  # names are drawn as plain text


def test_pdf_without_statistics_still_has_the_report_and_daily_chart(plain_pdf):
    pdf = pdf_of(replace(report_with_data(), statistics=None))
    for text in EXISTING + (b"Daily completion",):
        assert text in pdf, text.decode()
    for text in (b"Statistics overview", b"Adherence heatmap", b"Medication completion"):
        assert text not in pdf


def test_pdf_handles_empty_statistics(plain_pdf):
    pdf = pdf_of(replace(report_with_data(), statistics=stats_with()))
    assert b"No completion data yet" in pdf and b"No data yet." in pdf
    assert b"0/0 doses" in pdf and b"0 days" in pdf


def test_pdf_handles_perfect_and_zero_values(plain_pdf):
    base = report_with_data()
    perfect = stats_with(
        (480, 480), (30, 30), heat_days(120, ratio=lambda i: 1), [("Biotin", 120, 120)], (120, 120)
    )
    zero = stats_with(
        (0, 480), (0, 30), heat_days(120, ratio=lambda i: 0), [("Biotin", 0, 120)], (0, 0), 120
    )
    assert b"100%" in pdf_of(replace(base, statistics=perfect))
    assert b"0/480 doses" in pdf_of(replace(base, statistics=zero))
    assert b"1 day)" in pdf_of(replace(base, statistics=stats_with(streaks=(1, 1))))


def test_pdf_handles_day_gaps_and_short_heatmaps(plain_pdf):
    base = report_with_data()
    gaps = [d for i, d in enumerate(heat_days(120)) if i % 7 not in (2, 3)]
    for days in (gaps, heat_days(1), heat_days(8, end="2026-01-04")):
        assert b"Adherence heatmap" in pdf_of(replace(base, statistics=stats_with(heatmap=days)))


def test_pdf_paginates_many_medications_with_very_long_names(plain_pdf):
    base = report_with_data()
    names = [f"Extended release hydrochloride tablets {'x' * 90} number {i}" for i in range(14)]
    names += [f"Medication {i}" for i in range(14, 30)]
    report = replace(
        base,
        medications=tuple(MedicationReport(n, 7, i % 8) for i, n in enumerate(names)),
        statistics=stats_with(
            (300, 400),
            (30, 40),
            heat_days(120),
            [(n, 100, (i * 3) % 101) for i, n in enumerate(names)],
        ),
    )
    pdf = pdf_of(report)
    assert b"Page 3" in pdf
    assert b"Medication 29" in pdf
    assert b"..." in pdf  # long bar names are cut, not overflowed


def test_pdf_renders_a_period_with_no_doses():
    report = report_with_data()
    empty_days = tuple(replace(d, total=0, taken=0, missed=()) for d in report.days)
    pdf_of(replace(report, days=empty_days, medications=()))


def test_text_body_mentions_the_statistics_when_present():
    report = Setup().build(datetime(2026, 1, 7, 4, 30, tzinfo=UTC))
    text = render_text(report, "Medication Tracker", "me@example.com")
    assert "Last 120 days:" in text and "attached PDF" in text
    assert "Last 120 days" not in render_text(replace(report, statistics=None), "App", "a@b.c")


def test_pdf_prints_a_question_mark_for_characters_helvetica_cannot_draw(plain_pdf):
    base = report_with_data()
    name = "दवा Pill 💊"
    report = replace(
        base,
        medications=(MedicationReport(name, 4, 3),),
        statistics=stats_with((3, 4), meds=[(name, 3, 4)]),
    )
    pdf = pdf_of(report)
    assert b"??? Pill ?" in pdf
