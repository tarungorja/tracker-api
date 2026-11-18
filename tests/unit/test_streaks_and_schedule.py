from app.utils.schedule import dose_status, is_medication_due_on, normalize_days
from app.utils.streaks import current_streak, longest_streak


def test_longest_streak():
    keys = ["a", "b", "c", "d", "e", "f"]
    good = {"a", "b", "d", "e", "f"}
    assert longest_streak(keys, good.__contains__) == 3


def test_current_streak_with_grace_for_open_today():
    done = {"2026-01-03", "2026-01-04"}
    assert current_streak("2026-01-05", done.__contains__, grace_today=True) == 2
    assert current_streak("2026-01-05", done.__contains__, grace_today=False) == 0
    done.add("2026-01-05")
    assert current_streak("2026-01-05", done.__contains__, grace_today=False) == 3


def test_normalize_days():
    assert normalize_days([3, 1, 1, 9, -1]) == [1, 3]
    assert normalize_days(None) == [0, 1, 2, 3, 4, 5, 6]
    assert normalize_days([]) == [0, 1, 2, 3, 4, 5, 6]


def test_is_medication_due_on():
    assert is_medication_due_on([1], "2026-01-05")  # Monday
    assert not is_medication_due_on([1], "2026-01-06")


def test_dose_status():
    assert dose_status(True, 600, 700, True) == "completed"
    assert dose_status(False, 800, 700, True) == "upcoming"
    assert dose_status(False, 600, 700, True) == "missed"
    assert dose_status(False, 800, 700, False) == "missed"
