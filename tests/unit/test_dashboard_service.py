from app.schemas.dose import DoseView
from app.services.dashboard_service import compute_next_reminder


def dose(name: str, minutes: int, completed: bool = False) -> DoseView:
    return DoseView(
        medication_name=name,
        scheduled_time=f"{minutes}",
        scheduled_minutes=minutes,
        completed=completed,
        completed_at=None,
    )


def test_next_reminder_is_next_pending_dose_today():
    doses = [dose("A", 480, True), dose("B", 600), dose("C", 1200)]
    result = compute_next_reminder(doses, now_minutes=540)
    assert (result.medication_name, result.minutes_until, result.is_tomorrow) == ("B", 60, False)


def test_next_reminder_wraps_to_tomorrow():
    doses = [dose("A", 480, True), dose("B", 600, True)]
    result = compute_next_reminder(doses, now_minutes=1300)
    assert result.is_tomorrow
    assert result.medication_name == "A"
    assert result.minutes_until == 24 * 60 - 1300 + 480


def test_next_reminder_none_without_doses():
    assert compute_next_reminder([], 100) is None
