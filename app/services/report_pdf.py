"""Renders an adherence report as an A4 PDF.

Besides the 7-day report itself (summary, day by day, by medication) it carries the numbers and
charts of the Statistics page, in the same colours.
"""

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.schemas.statistics import StatisticsData
from app.services import report_charts as charts
from app.services.report_charts import (
    A_AMBER,
    A_BLUE,
    A_BRAND,
    A_GREEN,
    A_ROSE,
    A_VIOLET,
    BLUE,
    BRAND,
    INK,
    LINE,
    MUTED,
    VIOLET,
    Accent,
    CompletionBar,
    SectionHeading,
    Tile,
    hex_of,
    mix,
    tone,
)
from app.services.report_render import Report, percent
from app.utils.time import short_date_label

PAGE_MARGIN = 20 * mm
CONTENT_WIDTH = A4[0] - 2 * PAGE_MARGIN
GAP = 8

_base = getSampleStyleSheet()["Normal"]


def _style(name: str, **kwargs: object) -> ParagraphStyle:
    options: dict[str, object] = {"fontName": "Helvetica", "textColor": INK, **kwargs}
    return ParagraphStyle(name, parent=_base, **options)


TITLE = _style("title", fontName="Helvetica-Bold", fontSize=20, leading=24)
SUB = _style("sub", fontSize=10, leading=14, textColor=MUTED)
CELL = _style("cell", fontSize=9.5, leading=13)
CELL_MUTED = _style("cellm", fontSize=8.5, leading=12, textColor=MUTED)
HEAD = _style("head", fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=A_BRAND.text)
HEAD_R = ParagraphStyle("headr", parent=HEAD, alignment=TA_RIGHT)
RIGHT = ParagraphStyle("right", parent=CELL, alignment=TA_RIGHT)
NOTE = _style("note", fontSize=8, leading=11, textColor=MUTED)
TILE_VALUE = _style("tv", fontName="Helvetica-Bold", fontSize=20, leading=24, alignment=TA_CENTER)
TILE_LABEL = _style("tl", fontSize=8.5, leading=12, textColor=MUTED, alignment=TA_CENTER)
CARD_LABEL = _style("cl", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=MUTED)
CARD_VALUE = _style("cv", fontName="Helvetica-Bold", fontSize=19, leading=23)
CARD_HINT = _style("ch", fontSize=8, leading=11, textColor=MUTED)
RING_LABEL = _style("rl", fontSize=9, leading=12, textColor=MUTED)
RING_VALUE = _style("rv", fontName="Helvetica-Bold", fontSize=14, leading=18)


def _p(text: str, style: ParagraphStyle = CELL) -> Paragraph:
    return Paragraph(escape(charts.winansi(text)), style)


def _colored(text: str, color: colors.Color, style: ParagraphStyle = CELL) -> Paragraph:
    return Paragraph(
        f'<font color="{hex_of(color)}"><b>{escape(charts.winansi(text))}</b></font>', style
    )


def _no_padding() -> list[tuple[str, tuple[int, int], tuple[int, int], int]]:
    return [
        (name, (0, 0), (-1, -1), 0)
        for name in ("LEFTPADDING", "RIGHTPADDING", "TOPPADDING", "BOTTOMPADDING")
    ]


def _grid(header: list[Flowable], rows: list[list[Flowable]], widths: list[float]) -> Table:
    table = Table([header, *rows], colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, 0), mix(BRAND, 0.08)),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, mix(BRAND, 0.03)]),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, mix(BRAND, 0.35)),
                ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _row(tiles: list[Flowable]) -> Table:
    """Tiles side by side with a gap between them."""
    cell = (CONTENT_WIDTH - GAP * (len(tiles) - 1)) / len(tiles)
    cells: list[Flowable] = []
    widths: list[float] = []
    for i, tile in enumerate(tiles):
        if i:
            cells.append(Spacer(GAP, 1))
            widths.append(GAP)
        cells.append(tile)
        widths.append(cell)
    table = Table([cells], colWidths=widths)
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), *_no_padding()]))
    return table


def _summary(report: Report) -> Table:
    cells: list[tuple[str, str, Accent]] = [
        (f"{report.percent}%", "Adherence", tone(report.percent)),
        (f"{report.taken}/{report.total}", "Doses taken", A_BRAND),
        (str(report.missed_count), "Doses missed", A_ROSE if report.missed_count else A_GREEN),
        (f"{report.perfect_days}/{len(report.days)}", "Perfect days", A_VIOLET),
    ]
    return _row(
        [
            Tile(
                [
                    Paragraph(
                        f'<font color="{hex_of(accent.text)}">{escape(value)}</font>', TILE_VALUE
                    ),
                    Paragraph(escape(label), TILE_LABEL),
                ],
                accent,
                height=58,
            )
            for value, label, accent in cells
        ]
    )


def _ring_tile(
    label: str, percent_value: int, completed: int, total: int, caption: str, accent: Accent
) -> Tile:
    gauge = charts.ring(percent_value, 76, 9, accent)
    text = [
        Paragraph(escape(label), RING_LABEL),
        Paragraph(f"{completed}/{total} doses", RING_VALUE),
        Paragraph(escape(caption), CARD_HINT),
    ]
    inner = Table([[gauge, text]], colWidths=[76 + 14, None])
    inner.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), *_no_padding()]))
    return Tile([inner], accent, height=92, tint=0.07)


def _metric_tile(label: str, value: str, hint: str, accent: Accent) -> Tile:
    return Tile(
        [
            Paragraph(escape(label.upper()), CARD_LABEL),
            Paragraph(f'<font color="{hex_of(accent.text)}">{escape(value)}</font>', CARD_VALUE),
            Paragraph(escape(hint), CARD_HINT),
        ],
        accent,
        height=60,
        tint=0.1,
    )


def _days(count: int) -> str:
    return f"{count} day" if count == 1 else f"{count} days"


def _table_heading(title: str) -> list[Flowable]:
    """A heading that starts a new page only when little room is left, so tables can split."""
    heading = SectionHeading(title)
    heading.keepWithNext = False
    return [CondPageBreak(45 * mm), heading]


def _statistics_overview(stats: StatisticsData) -> list[Flowable]:
    rings = _row(
        [
            _ring_tile(
                "Overall completion",
                stats.overall_percent,
                stats.overall_completed,
                stats.overall_total,
                "Last 120 days",
                A_BRAND,
            ),
            _ring_tile(
                "This month",
                stats.month_percent,
                stats.month_completed,
                stats.month_total,
                "Since the 1st",
                A_BLUE,
            ),
        ]
    )
    metrics = _row(
        [
            _metric_tile("Current streak", _days(stats.current_streak), "Days in a row", A_ROSE),
            _metric_tile(
                "Longest streak", _days(stats.longest_streak), "Best run, last 120 days", A_VIOLET
            ),
            _metric_tile(
                "Missed doses", str(stats.missed_reminders), "Not taken before today", A_AMBER
            ),
        ]
    )
    return [
        KeepTogether(
            [SectionHeading("Statistics overview", "Last 120 days"), rings, Spacer(1, GAP), metrics]
        )
    ]


def _medication_completion(stats: StatisticsData) -> list[Flowable]:
    heading = SectionHeading("Medication completion", "Last 120 days")
    if not stats.medication_stats:
        return [
            heading,
            _p("No completion data yet. Start checking off doses to see stats here.", CELL_MUTED),
        ]
    bars = [CompletionBar(m.name, m.completed, m.total, m.percent) for m in stats.medication_stats]
    return [KeepTogether([heading, *bars[:3]]), *bars[3:]]


def _heatmap(stats: StatisticsData) -> list[Flowable]:
    heading = SectionHeading("Adherence heatmap", "Last 120 days")
    if not stats.heatmap:
        return [heading, _p("No data yet.", CELL_MUTED)]
    return [KeepTogether([heading, charts.heatmap(stats.heatmap, CONTENT_WIDTH)])]


def _header_footer(app_name: str):
    def draw(canvas: Canvas, doc: BaseDocTemplate) -> None:
        canvas.saveState()
        left, right, y = PAGE_MARGIN, A4[0] - PAGE_MARGIN, A4[1] - 12 * mm
        span = right - left
        canvas.setLineWidth(2)
        for start, end, color in ((0, 0.6, BRAND), (0.6, 0.85, VIOLET), (0.85, 1, BLUE)):
            canvas.setStrokeColor(color)
            canvas.line(left + span * start, y, left + span * end, y)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(left, 10 * mm, app_name)
        canvas.drawRightString(right, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    return draw


def render_pdf(report: Report, app_name: str, email: str) -> bytes:
    buffer = BytesIO()
    top, bottom = 20 * mm, 18 * mm
    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        title=f"{app_name} report {report.range_label}",
        author=app_name,
    )
    # No frame padding, so tiles, charts and text all share the page margins.
    frame = Frame(
        PAGE_MARGIN,
        bottom,
        CONTENT_WIDTH,
        A4[1] - top - bottom,
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    doc.addPageTemplates([PageTemplate("report", [frame], onPage=_header_footer(app_name))])
    width = CONTENT_WIDTH

    day_rows: list[list[Flowable]] = []
    for day in report.days:
        if day.total == 0:
            status = _p("No doses scheduled", CELL_MUTED)
        elif day.taken == day.total:
            status = _colored("All taken", A_GREEN.text)
        else:
            amber = hex_of(A_AMBER.text)
            missed = escape(charts.winansi(", ".join(day.missed)))
            status = Paragraph(
                f'<font color="{amber}"><b>{day.taken}/{day.total} taken</b></font><br/>'
                f'<font color="#71717a" size="8.5">Missed: {missed}</font>',
                CELL,
            )
        day_rows.append([_p(f"{day.weekday}, {short_date_label(day.date)}"), status])

    med_rows: list[list[Flowable]] = []
    for m in report.medications:
        pct = percent(m.taken, m.total)
        med_rows.append(
            [
                _p(m.name),
                _p(f"{m.taken}/{m.total}", RIGHT),
                charts.mini_bar(pct, width * 0.2),
                _colored(f"{pct}%", tone(pct).text, RIGHT),
            ]
        )

    story: list[Flowable] = [
        _p("Medication adherence report", TITLE),
        Spacer(1, 3),
        _p(f"{report.range_label}  \xb7  {email}", SUB),
        Spacer(1, 12),
        _summary(report),
    ]
    if report.statistics is not None:
        story += _statistics_overview(report.statistics)
    story += [
        SectionHeading("Daily completion", report.range_label, A_GREEN),
        charts.daily_chart(report.days, width),
        *_table_heading("Day by day"),
        _grid([_p("Day", HEAD), _p("Doses", HEAD)], day_rows, [width * 0.28, width * 0.72]),
        *_table_heading("By medication"),
        _grid(
            [_p("Medication", HEAD), _p("Taken", HEAD_R), _p("", HEAD), _p("Adherence", HEAD_R)],
            med_rows,
            [width * 0.44, width * 0.16, width * 0.24, width * 0.16],
        ),
    ]
    if report.statistics is not None:
        story += _medication_completion(report.statistics)
        story += _heatmap(report.statistics)
    story += [
        Spacer(1, 14),
        _p(
            "Based on current active medications and the doses marked as taken. "
            "Today only counts doses that are already due.",
            NOTE,
        ),
    ]
    doc.build(story)
    return buffer.getvalue()
