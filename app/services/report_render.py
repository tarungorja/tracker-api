"""Renders an adherence report as the HTML email body and a plain-text alternative."""

from dataclasses import dataclass
from html import escape

from app.schemas.statistics import StatisticsData
from app.utils.numbers import round_half_up
from app.utils.time import short_date_label


def percent(taken: int, total: int) -> int:
    return int(round_half_up(taken / total * 100)) if total > 0 else 0


@dataclass(frozen=True)
class DayReport:
    date: str
    weekday: str
    total: int
    taken: int
    missed: tuple[str, ...]
    """Missed doses as "Biotin (8:00 AM)"."""


@dataclass(frozen=True)
class MedicationReport:
    name: str
    total: int
    taken: int


@dataclass(frozen=True)
class Report:
    start_date: str
    end_date: str
    days: tuple[DayReport, ...]
    medications: tuple[MedicationReport, ...]
    statistics: StatisticsData | None = None
    """The Statistics page numbers (last 120 days). Without them the PDF skips those sections."""

    @property
    def total(self) -> int:
        return sum(d.total for d in self.days)

    @property
    def taken(self) -> int:
        return sum(d.taken for d in self.days)

    @property
    def missed_count(self) -> int:
        return self.total - self.taken

    @property
    def percent(self) -> int:
        return percent(self.taken, self.total)

    @property
    def perfect_days(self) -> int:
        return sum(1 for d in self.days if d.total > 0 and d.taken == d.total)

    @property
    def range_label(self) -> str:
        start, end = short_date_label(self.start_date), short_date_label(self.end_date)
        return f"{start} – {end}, {self.end_date[:4]}"


def report_subject(report: Report, app_name: str) -> str:
    return f"{app_name} report: {report.range_label}"


def report_filename(report: Report) -> str:
    return f"medication-report-{report.start_date}_to_{report.end_date}.pdf"


def _tone(value: int) -> str:
    """Same thresholds as the Statistics page and the PDF: green from 80%, amber from 50%."""
    if value >= 80:
        return "#16a34a"
    return "#d97706" if value >= 50 else "#dc2626"


def render_text(report: Report, app_name: str, email: str) -> str:
    lines = [
        f"{app_name}: weekly report for {email}",
        report.range_label,
        "",
        f"Taken {report.taken} of {report.total} doses ({report.percent}%). "
        f"Missed {report.missed_count}. Perfect days: {report.perfect_days} of {len(report.days)}.",
        "",
        "Day by day",
    ]
    for day in report.days:
        row = f"  {day.weekday} {short_date_label(day.date)}: {day.taken}/{day.total} taken"
        lines.append(row + (f" - missed {', '.join(day.missed)}" if day.missed else ""))
    lines += ["", "By medication"]
    lines += [
        f"  {m.name}: {m.taken}/{m.total} ({percent(m.taken, m.total)}%)"
        for m in report.medications
    ]
    if report.statistics is not None:
        stats = report.statistics
        lines += [
            "",
            f"Last 120 days: {stats.overall_percent}% complete, current streak "
            f"{stats.current_streak}, longest streak {stats.longest_streak}. "
            "Charts and the heatmap are in the attached PDF.",
        ]
    return "\n".join(lines)


def render_html(report: Report, app_name: str, email: str) -> str:
    """Inline styles only, so it renders in mail clients."""
    e = escape
    tone = _tone(report.percent)

    def stat(label: str, value: str, color: str = "#18181b") -> str:
        return (
            '<td style="padding:12px;text-align:center;background:#f4f4f5;border-radius:12px">'
            f'<div style="font-size:24px;font-weight:700;color:{color}">{value}</div>'
            f'<div style="font-size:12px;color:#71717a;margin-top:2px">{label}</div></td>'
        )

    day_rows = ""
    for day in report.days:
        if day.total == 0:
            status = '<span style="color:#a1a1aa">No doses</span>'
        elif day.taken == day.total:
            status = '<span style="color:#16a34a;font-weight:600">All taken</span>'
        else:
            status = (
                f'<span style="color:#d97706;font-weight:600">{day.taken}/{day.total} taken</span>'
                f'<div style="color:#71717a;font-size:12px;margin-top:2px">Missed: '
                f"{e(', '.join(day.missed))}</div>"
            )
        day_rows += (
            '<tr><td style="padding:10px 12px;border-top:1px solid #e4e4e7;white-space:nowrap;'
            f'vertical-align:top;color:#3f3f46">{e(day.weekday)}, {e(short_date_label(day.date))}'
            f'</td><td style="padding:10px 12px;border-top:1px solid #e4e4e7">{status}</td></tr>'
        )

    med_rows = ""
    for med in report.medications:
        pct = percent(med.taken, med.total)
        med_rows += (
            '<tr><td style="padding:10px 12px;border-top:1px solid #e4e4e7;color:#3f3f46">'
            f"{e(med.name)}</td>"
            '<td style="padding:10px 12px;border-top:1px solid #e4e4e7;text-align:right;'
            f'white-space:nowrap;color:{_tone(pct)};font-weight:600">{med.taken}/{med.total} '
            f"({pct}%)</td></tr>"
        )

    th = 'style="padding:8px 12px;text-align:left;font-size:12px;color:#71717a;font-weight:600"'
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{e(report_subject(report, app_name))}</title></head>"
        '<body style="margin:0;background:#ffffff">'
        '<div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;'
        'max-width:640px;margin:0 auto;padding:24px;color:#18181b">'
        f'<h1 style="margin:0;font-size:20px">{e(app_name)}</h1>'
        f'<p style="margin:4px 0 20px;color:#52525b">Report for {e(email)}<br>'
        f"{e(report.range_label)}</p>"
        '<table role="presentation" width="100%" cellspacing="8" style="border-collapse:separate;'
        'margin:0 -8px 16px"><tr>'
        + stat("Adherence", f"{report.percent}%", tone)
        + stat("Taken", f"{report.taken}/{report.total}")
        + stat("Missed", str(report.missed_count), "#dc2626" if report.missed_count else "#18181b")
        + stat("Perfect days", f"{report.perfect_days}/{len(report.days)}")
        + "</tr></table>"
        '<h2 style="font-size:15px;margin:20px 0 6px">Day by day</h2>'
        '<table width="100%" cellspacing="0" style="border-collapse:collapse;font-size:14px">'
        f"<tr><th {th}>Day</th><th {th}>Doses</th></tr>{day_rows}</table>"
        '<h2 style="font-size:15px;margin:24px 0 6px">By medication</h2>'
        '<table width="100%" cellspacing="0" style="border-collapse:collapse;font-size:14px">'
        f"<tr><th {th}>Medication</th><th {th.replace('left', 'right')}>Taken</th></tr>"
        f"{med_rows}</table>"
        '<p style="margin:24px 0 0;color:#a1a1aa;font-size:12px">Based on your current active '
        "medications and the doses you marked as taken. Today only counts doses already due.</p>"
        "</div></body></html>"
    )
