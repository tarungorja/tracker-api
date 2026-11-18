from datetime import UTC, datetime

import pytest

from app.utils import time as t


@pytest.mark.parametrize(
    ("label", "minutes"),
    [
        ("2:30 PM", 14 * 60 + 30),
        ("12:00 AM", 0),
        ("12:15 PM", 12 * 60 + 15),
        ("14:30", 14 * 60 + 30),
        ("9:05am", 9 * 60 + 5),
        ("  8:00 PM ", 20 * 60),
    ],
)
def test_parse_schedule_valid(label, minutes):
    assert t.parse_schedule_to_minutes(label) == minutes


@pytest.mark.parametrize("label", ["", "25:00", "10:75", "abc", "10", "10:00 XM"])
def test_parse_schedule_invalid(label):
    assert t.parse_schedule_to_minutes(label) is None


def test_normalize_schedule_label():
    assert t.normalize_schedule_label("14:00") == "2:00 PM"
    assert t.normalize_schedule_label("08:05 am") == "8:05 AM"
    assert t.normalize_schedule_label(" nonsense ") == "nonsense"


def test_ist_date_rolls_over_at_utc_1830():
    before = datetime(2026, 1, 5, 18, 29, tzinfo=UTC)
    after = datetime(2026, 1, 5, 18, 30, tzinfo=UTC)
    assert t.ist_date_key(before) == "2026-01-05"
    assert t.ist_date_key(after) == "2026-01-06"
    assert t.ist_minutes_of_day(after) == 0


def test_date_key_arithmetic():
    assert t.add_days_to_key("2026-03-01", -1) == "2026-02-28"
    assert t.date_key_range("2026-01-30", "2026-02-02") == [
        "2026-01-30",
        "2026-01-31",
        "2026-02-01",
        "2026-02-02",
    ]
    assert t.days_between_keys("2026-01-01", "2026-01-31") == 30


def test_weekday_is_sunday_based():
    assert t.weekday_of_key("2026-01-04") == 0  # Sunday
    assert t.weekday_of_key("2026-01-05") == 1  # Monday
    assert t.weekday_of_key("2026-01-10") == 6  # Saturday


def test_short_label_and_iso_z():
    assert t.short_date_label("2026-11-05") == "Nov 5"
    moment = datetime(2026, 1, 5, 8, 30, 1, 234_000, tzinfo=UTC)
    assert t.to_iso_z(moment) == "2026-01-05T08:30:01.234Z"


def test_is_valid_date_key():
    assert t.is_valid_date_key("2026-02-28")
    assert not t.is_valid_date_key("2026-02-30")
    assert not t.is_valid_date_key("2026-2-3")
