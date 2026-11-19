"""Pure logic behind the PDF charts: colour thresholds, heatmap levels, layout helpers."""

from reportlab.pdfbase.pdfmetrics import stringWidth

from app.schemas.dose import DayCompletion
from app.services import report_charts as charts


def test_tone_uses_the_statistics_page_thresholds():
    assert [charts.tone(v) for v in (100, 80, 79, 50, 49, 0)] == [
        charts.A_GREEN,
        charts.A_GREEN,
        charts.A_AMBER,
        charts.A_AMBER,
        charts.A_ROSE,
        charts.A_ROSE,
    ]


def test_heatmap_levels_match_the_app():
    ratios = (0, 0.1, 0.33, 0.34, 0.66, 0.67, 0.99, 1)
    assert [charts.heatmap_level(v) for v in ratios] == [0, 1, 1, 2, 2, 3, 3, 4]
    assert len(charts.heatmap_fills()) == 5


def test_fit_text_truncates_only_when_needed():
    assert charts.fit_text("Biotin", "Helvetica", 9, 200) == "Biotin"
    cut = charts.fit_text("A very long medication name " * 5, "Helvetica", 9, 100)
    assert cut.endswith("...") and stringWidth(cut, "Helvetica", 9) <= 100
    assert charts.fit_text("Anything", "Helvetica", 9, 1) == "..."


def test_weeks_are_sunday_first_and_padded():
    # 2026-01-01 is a Thursday: four empty cells, then Thu..Sat; Jan 4 starts the next week.
    days = [DayCompletion(date=f"2026-01-0{d}", total=1, completed=1, ratio=1) for d in range(1, 8)]
    weeks = charts._weeks(days)
    assert [len(w) for w in weeks] == [7, 7]
    assert [d is None for d in weeks[0]] == [True] * 4 + [False] * 3
    assert weeks[1][3] is not None and weeks[1][4] is None  # Wed Jan 7 is the last cell


def test_mix_blends_towards_white():
    assert charts.mix(charts.GREEN, 1) == charts.GREEN
    white = charts.mix(charts.GREEN, 0)
    assert (white.red, white.green, white.blue) == (1, 1, 1)


def test_winansi_replaces_what_helvetica_cannot_draw():
    assert charts.winansi("Biotin B12 é · €") == "Biotin B12 é · €"
    assert charts.winansi("Pill 💊") == "Pill ?"
    assert charts.winansi("दवा") == "???"
