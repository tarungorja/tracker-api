"""Colours, tiles and charts for the PDF report.

The palette and thresholds mirror the Statistics page of the web and mobile apps (brand purple, the
green / amber / rose accents, the five-step green heatmap), so the report reads as the same
product. Only built-in Helvetica is used, so every string must stay within WinAnsi.
"""

import colorsys
from collections.abc import Sequence
from dataclasses import dataclass
from math import cos, radians, sin

from reportlab.graphics.shapes import Circle, Drawing, Line, Rect, String, Wedge
from reportlab.lib import colors
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Flowable

from app.schemas.dose import DayCompletion
from app.services.report_render import DayReport, percent
from app.utils.time import short_date_label, weekday_of_key

HEATMAP_LEGEND = ("Less", "More")
WEEKDAY_INITIALS = ("S", "M", "T", "W", "T", "F", "S")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _hsl(h: float, s: float, light: float) -> colors.Color:
    r, g, b = colorsys.hls_to_rgb(h / 360, light / 100, s / 100)
    return colors.Color(r, g, b)


def mix(color: colors.Color, alpha: float) -> colors.Color:
    """`color` at `alpha` opacity over a white page."""
    return colors.Color(
        1 - alpha * (1 - color.red), 1 - alpha * (1 - color.green), 1 - alpha * (1 - color.blue)
    )


def hex_of(color: colors.Color) -> str:
    return "#" + color.hexval()[2:]


# Same values as the app's design tokens (light theme).
INK = _hsl(240, 10, 12)
MUTED = colors.HexColor("#71717a")
LINE = _hsl(240, 12, 90)
SECONDARY = _hsl(240, 12, 96)
BRAND = _hsl(250, 84, 60)
ROSE = _hsl(347, 86, 61)
AMBER = _hsl(38, 92, 55)
GREEN = _hsl(145, 63, 45)
BLUE = _hsl(205, 90, 55)
VIOLET = _hsl(262, 83, 62)


@dataclass(frozen=True)
class Accent:
    """A page accent and the darker shade used when it colours small text on white."""

    fill: colors.Color
    text: colors.Color


A_BRAND = Accent(BRAND, colors.HexColor("#4f35d2"))
A_GREEN = Accent(GREEN, colors.HexColor("#15803d"))
A_AMBER = Accent(AMBER, colors.HexColor("#b45309"))
A_ROSE = Accent(ROSE, colors.HexColor("#be123c"))
A_BLUE = Accent(BLUE, colors.HexColor("#0369a1"))
A_VIOLET = Accent(VIOLET, colors.HexColor("#6d28d9"))
A_NEUTRAL = Accent(MUTED, INK)


def tone(percent_value: int) -> Accent:
    """Completion colour: green from 80%, amber from 50%, rose below (as on the Statistics page)."""
    if percent_value >= 80:
        return A_GREEN
    return A_AMBER if percent_value >= 50 else A_ROSE


def heatmap_level(ratio: float) -> int:
    if ratio <= 0:
        return 0
    if ratio < 0.34:
        return 1
    if ratio < 0.67:
        return 2
    return 3 if ratio < 1 else 4


_HEAT_ALPHAS = (0.25, 0.45, 0.70, 1.0)


def heatmap_fills() -> list[colors.Color]:
    return [SECONDARY, *(mix(GREEN, a) for a in _HEAT_ALPHAS)]


def winansi(text: str) -> str:
    """`text` with every character the built-in Helvetica cannot draw replaced by "?".

    Without this, names in other scripts or emoji print as solid black boxes. Bundling a Unicode
    font would be the real fix; until then an unreadable character is at least visibly degraded.
    """
    return text.encode("cp1252", errors="replace").decode("cp1252")


def fit_text(text: str, font: str, size: float, max_width: float) -> str:
    """`text` cut with "..." so it is at most `max_width` points wide."""
    if stringWidth(text, font, size) <= max_width:
        return text
    ellipsis = "..."
    while text and stringWidth(text + ellipsis, font, size) > max_width:
        text = text[:-1]
    return text.rstrip() + ellipsis


# ---- flowables ----------------------------------------------------------------------------


class SectionHeading(Flowable):
    """A coloured marker, the section title and an optional right-aligned caption."""

    HEIGHT = 17

    def __init__(self, title: str, caption: str = "", accent: Accent = A_BRAND) -> None:
        super().__init__()
        self.title, self.caption, self.accent = title, caption, accent
        self.spaceBefore = 14
        self.spaceAfter = 6
        self.keepWithNext = True
        self._width = 0.0

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
        self._width = availWidth
        return availWidth, self.HEIGHT

    def draw(self) -> None:
        c = self.canv
        c.setFillColor(self.accent.fill)
        c.roundRect(0, 1, 4, 14, 2, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(11, 4, self.title)
        if self.caption:
            c.setFillColor(MUTED)
            c.setFont("Helvetica", 8.5)
            c.drawRightString(self._width, 4, self.caption)


class Tile(Flowable):
    """A rounded, softly tinted card that centres its content."""

    def __init__(
        self,
        content: Sequence[Flowable],
        accent: Accent,
        height: float,
        pad: float = 10,
        tint: float = 0.09,
    ) -> None:
        super().__init__()
        self.content = list(content)
        self.accent, self.height, self.pad, self.tint = accent, height, pad, tint
        self._width = 0.0

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
        self._width = availWidth
        return availWidth, self.height

    def draw(self) -> None:
        c = self.canv
        c.setFillColor(mix(self.accent.fill, self.tint))
        c.setStrokeColor(mix(self.accent.fill, 0.28))
        c.setLineWidth(0.6)
        c.roundRect(0.3, 0.3, self._width - 0.6, self.height - 0.6, 8, stroke=1, fill=1)
        inner = self._width - 2 * self.pad
        sizes = [f.wrapOn(c, inner, 10_000) for f in self.content]
        y = (self.height + sum(h for _, h in sizes)) / 2
        for f, (_, h) in zip(self.content, sizes, strict=True):
            y -= h
            f.drawOn(c, self.pad, y)


class CompletionBar(Flowable):
    """One medication: name, "completed/total · pct%" and a coloured progress bar."""

    HEIGHT = 30

    def __init__(self, name: str, completed: int, total: int, pct: int) -> None:
        super().__init__()
        self.name, self.completed, self.total, self.pct = name, completed, total, pct
        self._width = 0.0

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
        self._width = availWidth
        return availWidth, self.HEIGHT

    def draw(self) -> None:
        c, w = self.canv, self._width
        accent = tone(self.pct)
        detail = f"{self.completed}/{self.total}  \xb7  {self.pct}%"
        c.setFont("Helvetica", 9)
        detail_w = stringWidth(detail, "Helvetica", 9)
        c.setFillColor(MUTED)
        c.drawRightString(w, 18, detail)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(0, 18, fit_text(winansi(self.name), "Helvetica-Bold", 9.5, w - detail_w - 12))
        c.setFillColor(mix(accent.fill, 0.16))
        c.roundRect(0, 5, w, 7, 3.5, stroke=0, fill=1)
        if self.pct > 0:
            c.setFillColor(accent.fill)
            c.roundRect(0, 5, max(w * min(self.pct, 100) / 100, 7), 7, 3.5, stroke=0, fill=1)


# ---- drawings -----------------------------------------------------------------------------


def ring(value: int, size: float, stroke: float, accent: Accent) -> Drawing:
    """A circular progress gauge, starting at 12 o'clock and running clockwise."""
    d = Drawing(size, size)
    cx = cy = size / 2
    mid = (size - stroke) / 2
    outer, inner = mid + stroke / 2, mid - stroke / 2
    share = max(0, min(100, value)) / 100
    d.add(
        Circle(cx, cy, mid, fillColor=None, strokeColor=mix(accent.fill, 0.2), strokeWidth=stroke)
    )
    if share >= 1:
        d.add(Circle(cx, cy, mid, fillColor=None, strokeColor=accent.fill, strokeWidth=stroke))
    elif share > 0:
        end = 90 - 360 * share
        d.add(Wedge(cx, cy, outer, end, 90, radius1=inner, fillColor=accent.fill, strokeColor=None))
        for angle in (90, end):  # rounded ends
            x, y = cx + mid * cos(radians(angle)), cy + mid * sin(radians(angle))
            d.add(Circle(x, y, stroke / 2, fillColor=accent.fill, strokeColor=None))
    d.add(
        String(
            cx,
            cy - size * 0.07,
            f"{max(0, min(100, value))}%",
            fontName="Helvetica-Bold",
            fontSize=size * 0.22,
            fillColor=INK,
            textAnchor="middle",
        )
    )
    return d


def daily_chart(days: Sequence[DayReport], width: float, height: float = 128) -> Drawing:
    """One bar per day for the report period, coloured by the day's completion."""
    d = Drawing(width, height)
    left, label_h, legend_h, top = 26, 30, 16, 14
    base = legend_h + label_h
    plot_h = height - base - top
    slot = (width - left) / max(len(days), 1)
    bar_w = min(slot * 0.56, 40)

    for pct in (0, 50, 100):
        y = base + plot_h * pct / 100
        d.add(
            Line(left - 4, y, width, y, strokeColor=LINE, strokeWidth=0.5, strokeDashArray=[2, 2])
        )
        d.add(
            String(
                left - 8,
                y - 2.5,
                f"{pct}%",
                fontName="Helvetica",
                fontSize=6.5,
                fillColor=MUTED,
                textAnchor="end",
            )
        )

    for i, day in enumerate(days):
        cx = left + slot * (i + 0.5)
        x = cx - bar_w / 2
        d.add(Rect(x, base, bar_w, plot_h, rx=3, ry=3, fillColor=SECONDARY, strokeColor=None))
        if day.total == 0:
            d.add(
                String(
                    cx,
                    base + plot_h / 2 - 2,
                    "No doses",
                    fontName="Helvetica",
                    fontSize=6.5,
                    fillColor=MUTED,
                    textAnchor="middle",
                )
            )
        else:
            pct = percent(day.taken, day.total)
            bar_h = max(plot_h * pct / 100, 2.5)
            d.add(
                Rect(x, base, bar_w, bar_h, rx=3, ry=3, fillColor=tone(pct).fill, strokeColor=None)
            )
            d.add(
                String(
                    cx,
                    base + plot_h + 4,
                    f"{pct}%",
                    fontName="Helvetica-Bold",
                    fontSize=8,
                    fillColor=tone(pct).text,
                    textAnchor="middle",
                )
            )
        counts = f"{day.taken}/{day.total}" if day.total else "-"
        for line, text, font, size, color in (
            (0, day.weekday, "Helvetica-Bold", 8, INK),
            (1, short_date_label(day.date), "Helvetica", 7, MUTED),
            (2, counts, "Helvetica", 7, MUTED),
        ):
            d.add(
                String(
                    cx,
                    base - 10 - line * 9,
                    text,
                    fontName=font,
                    fontSize=size,
                    fillColor=color,
                    textAnchor="middle",
                )
            )

    x = left
    for accent, text in ((A_GREEN, "80% and above"), (A_AMBER, "50-79%"), (A_ROSE, "Below 50%")):
        d.add(Circle(x + 3, 6, 3, fillColor=accent.fill, strokeColor=None))
        d.add(String(x + 10, 3.5, text, fontName="Helvetica", fontSize=7.5, fillColor=MUTED))
        x += 18 + stringWidth(text, "Helvetica", 7.5)
    return d


def _weeks(days: Sequence[DayCompletion]) -> list[list[DayCompletion | None]]:
    """Sunday-first week columns; the first and last are padded with empty cells."""
    weeks: list[list[DayCompletion | None]] = []
    column: list[DayCompletion | None] = [None] * weekday_of_key(days[0].date)
    for day in days:
        column.append(day)
        if weekday_of_key(day.date) == 6:
            weeks.append(column)
            column = []
    if column:
        weeks.append(column + [None] * (7 - len(column)))
    return weeks


def heatmap(days: Sequence[DayCompletion], width: float) -> Drawing:
    """Adherence heatmap: one column per week, one row per weekday, five green steps."""
    weeks = _weeks(days)
    label_w, month_h, legend_h = 16, 14, 20
    step = min((width - label_w) / len(weeks), 20)
    cell = step - 3
    grid_w = label_w + step * len(weeks)
    height = month_h + 7 * step + legend_h
    d = Drawing(width, height)
    x0 = (width - grid_w) / 2 + label_w
    top = height - month_h
    fills = heatmap_fills()

    # Month names sit over the week that holds the 1st; the opening column is named only when
    # there is room before the next month starts.
    marks: list[tuple[int, int]] = []
    for col, week in enumerate(weeks):
        month_start = next((day for day in week if day and day.date.endswith("-01")), None)
        if month_start is not None:
            marks.append((col, int(month_start.date[5:7])))
    first = next(day for day in weeks[0] if day is not None)
    if not marks or marks[0][0] >= 3:
        marks.insert(0, (0, int(first.date[5:7])))
    for col, month in marks:
        d.add(
            String(
                x0 + col * step,
                height - 9,
                _MONTHS[month - 1],
                fontName="Helvetica",
                fontSize=7,
                fillColor=MUTED,
            )
        )

    for row in (1, 3, 5):
        d.add(
            String(
                x0 - 6,
                top - row * step - cell / 2 - 2.5,
                WEEKDAY_INITIALS[row],
                fontName="Helvetica",
                fontSize=7,
                fillColor=MUTED,
                textAnchor="end",
            )
        )

    for col, week in enumerate(weeks):
        for row, day in enumerate(week):
            if day is None:
                continue
            level = heatmap_level(day.ratio)
            d.add(
                Rect(
                    x0 + col * step,
                    top - row * step - cell,
                    cell,
                    cell,
                    rx=2.5,
                    ry=2.5,
                    fillColor=fills[level],
                    strokeColor=LINE if level == 0 else None,
                    strokeWidth=0.4,
                )
            )

    legend_w = (
        2 * 18
        + 5 * 12
        + stringWidth(HEATMAP_LEGEND[0], "Helvetica", 7.5)
        + stringWidth(HEATMAP_LEGEND[1], "Helvetica", 7.5)
    )
    x = x0 + step * len(weeks) - legend_w
    d.add(String(x, 5, HEATMAP_LEGEND[0], fontName="Helvetica", fontSize=7.5, fillColor=MUTED))
    x += stringWidth(HEATMAP_LEGEND[0], "Helvetica", 7.5) + 6
    for fill in fills:
        d.add(
            Rect(
                x,
                4,
                9,
                9,
                rx=2,
                ry=2,
                fillColor=fill,
                strokeColor=LINE if fill is fills[0] else None,
                strokeWidth=0.4,
            )
        )
        x += 12
    d.add(String(x + 3, 5, HEATMAP_LEGEND[1], fontName="Helvetica", fontSize=7.5, fillColor=MUTED))
    return d


def mini_bar(pct: int, width: float) -> Drawing:
    """A slim progress bar that sits in a table row, level with a line of text."""
    width -= 8  # keeps clear of the neighbouring column
    d = Drawing(width, 13)
    accent = tone(pct)
    d.add(Rect(0, 3, width, 7, rx=3.5, ry=3.5, fillColor=mix(accent.fill, 0.16), strokeColor=None))
    if pct > 0:
        fill_w = max(width * min(pct, 100) / 100, 7)
        d.add(Rect(0, 3, fill_w, 7, rx=3.5, ry=3.5, fillColor=accent.fill, strokeColor=None))
    return d
