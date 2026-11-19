"""Renders an adherence report as an A4 PDF."""

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.report_render import Report, percent
from app.utils.time import short_date_label

INK = colors.HexColor("#18181b")
MUTED = colors.HexColor("#71717a")
LINE = colors.HexColor("#e4e4e7")
PANEL = colors.HexColor("#f4f4f5")
GREEN = colors.HexColor("#16a34a")
AMBER = colors.HexColor("#d97706")
RED = colors.HexColor("#dc2626")
BRAND = colors.HexColor("#6d5ce7")

_base = getSampleStyleSheet()["Normal"]


def _style(name: str, **kwargs: object) -> ParagraphStyle:
    options: dict[str, object] = {"fontName": "Helvetica", "textColor": INK, **kwargs}
    return ParagraphStyle(name, parent=_base, **options)


TITLE = _style("title", fontName="Helvetica-Bold", fontSize=20, leading=24)
SUB = _style("sub", fontSize=10, leading=14, textColor=MUTED)
H2 = _style("h2", fontName="Helvetica-Bold", fontSize=12, leading=16, spaceBefore=14, spaceAfter=6)
CELL = _style("cell", fontSize=9.5, leading=13)
CELL_MUTED = _style("cellm", fontSize=8.5, leading=12, textColor=MUTED)
HEAD = _style("head", fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=MUTED)
HEAD_R = ParagraphStyle("headr", parent=HEAD, alignment=TA_RIGHT)
RIGHT = ParagraphStyle("right", parent=CELL, alignment=TA_RIGHT)
NOTE = _style("note", fontSize=8, leading=11, textColor=MUTED)


def _tone(value: int) -> colors.Color:
    if value >= 90:
        return GREEN
    return AMBER if value >= 60 else RED


def _p(text: str, style: ParagraphStyle = CELL) -> Paragraph:
    return Paragraph(escape(text), style)


def _colored(text: str, color: colors.Color, style: ParagraphStyle = CELL) -> Paragraph:
    return Paragraph(
        f'<font color="{color.hexval().replace("0x", "#")}"><b>{escape(text)}</b></font>', style
    )


def _grid(header: list[Paragraph], rows: list[list[Paragraph]], widths: list[float]) -> Table:
    table = Table([header, *rows], colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, LINE),
                ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _summary(report: Report) -> Table:
    tone = _tone(report.percent)
    cells = [
        (f"{report.percent}%", "Adherence", tone),
        (f"{report.taken}/{report.total}", "Doses taken", INK),
        (str(report.missed_count), "Doses missed", RED if report.missed_count else INK),
        (f"{report.perfect_days}/{len(report.days)}", "Perfect days", INK),
    ]
    value_style = _style("v", fontName="Helvetica-Bold", fontSize=20, leading=24)
    flow = [
        [
            [
                Paragraph(
                    f'<font color="{c.hexval().replace("0x", "#")}">{escape(v)}</font>',
                    ParagraphStyle("vv", parent=value_style, alignment=1),
                ),
                Paragraph(escape(label), ParagraphStyle("ll", parent=CELL_MUTED, alignment=1)),
            ]
            for v, label, c in cells
        ]
    ]
    table = Table(flow, colWidths=[(A4[0] - 40 * mm) / 4] * 4)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PANEL),
                ("LINEAFTER", (0, 0), (-2, -1), 4, colors.white),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("ROUNDEDCORNERS", [6, 6, 6, 6]),
            ]
        )
    )
    return table


def _footer(app_name: str):
    def draw(canvas: Canvas, doc: SimpleDocTemplate) -> None:
        canvas.saveState()
        canvas.setStrokeColor(BRAND)
        canvas.setLineWidth(2)
        canvas.line(20 * mm, A4[1] - 12 * mm, A4[0] - 20 * mm, A4[1] - 12 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(20 * mm, 10 * mm, app_name)
        canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    return draw


def render_pdf(report: Report, app_name: str, email: str) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title=f"{app_name} report {report.range_label}",
        author=app_name,
    )
    width = A4[0] - 40 * mm

    day_rows: list[list[Paragraph]] = []
    for day in report.days:
        if day.total == 0:
            status = _p("No doses scheduled", CELL_MUTED)
        elif day.taken == day.total:
            status = _colored("All taken", GREEN)
        else:
            status = Paragraph(
                f'<font color="#d97706"><b>{day.taken}/{day.total} taken</b></font><br/>'
                f'<font color="#71717a" size="8.5">Missed: {escape(", ".join(day.missed))}</font>',
                CELL,
            )
        day_rows.append([_p(f"{day.weekday}, {short_date_label(day.date)}"), status])

    med_rows = [
        [
            _p(m.name),
            _p(f"{m.taken}/{m.total}", RIGHT),
            _colored(f"{percent(m.taken, m.total)}%", _tone(percent(m.taken, m.total)), RIGHT),
        ]
        for m in report.medications
    ]

    story = [
        _p("Medication adherence report", TITLE),
        Spacer(1, 3),
        _p(f"{report.range_label}  ·  {email}", SUB),
        Spacer(1, 12),
        _summary(report),
        _p("Day by day", H2),
        _grid([_p("Day", HEAD), _p("Doses", HEAD)], day_rows, [width * 0.28, width * 0.72]),
        _p("By medication", H2),
        _grid(
            [_p("Medication", HEAD), _p("Taken", HEAD_R), _p("Adherence", HEAD_R)],
            med_rows,
            [width * 0.58, width * 0.21, width * 0.21],
        ),
        Spacer(1, 14),
        _p(
            "Based on current active medications and the doses marked as taken. "
            "Today only counts doses that are already due.",
            NOTE,
        ),
    ]
    doc.build(story, onFirstPage=_footer(app_name), onLaterPages=_footer(app_name))
    return buffer.getvalue()
