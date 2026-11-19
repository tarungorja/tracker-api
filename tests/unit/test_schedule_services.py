"""Today / dashboard / medications / statistics / wellness against in-memory repositories."""

import asyncio
from datetime import UTC, datetime

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.schemas.dose import DoseCompletionInput
from app.schemas.medication import MedicationInput
from app.services.dashboard_service import DashboardService
from app.services.dose_service import DoseService
from app.services.medication_service import MedicationService
from app.services.schedule_service import ScheduleService
from app.services.statistics_service import StatisticsService
from app.services.today_service import TodayService
from app.services.wellness_service import WellnessService
from tests.fakes import FakeActivity, FakeDailyLogs, FakeMedications, med_doc

# Wednesday 2026-01-07, 10:00 IST (04:30 UTC).
NOW = datetime(2026, 1, 7, 4, 30, tzinfo=UTC)
TODAY = "2026-01-07"
USER = "u1"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def world():
    meds = FakeMedications(
        [
            med_doc(USER, "Biotin", ["8:00 AM", "8:00 PM"]),
            med_doc(USER, "Minoxidil", ["10:00 AM"], days=[1, 3, 5]),  # Mon/Wed/Fri
            med_doc(USER, "Weekend", ["9:00 AM"], days=[0, 6]),  # not due on a Wednesday
            med_doc(USER, "Paused", ["7:00 AM"], enabled=False),
            med_doc("someone-else", "Other", ["8:00 AM"]),
        ]
    )
    logs = FakeDailyLogs()
    logs.add_dose(USER, TODAY, "Biotin", "8:00 AM", True, NOW)
    schedule = ScheduleService(meds, logs)
    return meds, logs, schedule


def test_today_timeline(world):
    _, _, schedule = world
    data = run(TodayService(schedule).get(USER, NOW))

    assert data.today_key == TODAY
    assert data.now_minutes == 600
    assert [s.time for s in data.slots] == ["8:00 AM", "10:00 AM", "8:00 PM"]
    statuses = {d.scheduled_time: d.status for s in data.slots for d in s.doses}
    # 10:00 AM is "now": not strictly in the future, so it counts as missed until completed.
    assert statuses == {"8:00 AM": "completed", "10:00 AM": "missed", "8:00 PM": "upcoming"}
    assert (data.total, data.completed) == (3, 1)
    names = {d.medication_name for s in data.slots for d in s.doses}
    assert names == {"Biotin", "Minoxidil"}  # not Weekend (wrong day), Paused, or another user's


def test_dose_completed_at_is_millisecond_utc(world):
    _, _, schedule = world
    doses = run(schedule.doses_for_day(USER, TODAY))
    assert doses[0].completed_at == "2026-01-07T04:30:00.000Z"
    assert doses[1].completed_at is None


def test_dashboard_progress_next_reminder_and_streak(world):
    _, logs, schedule = world
    for day in ("2026-01-05", "2026-01-06"):
        logs.add_dose(USER, day, "Biotin", "8:00 AM")
        logs.add_dose(USER, day, "Biotin", "8:00 PM")

    data = run(DashboardService(schedule).get(USER, NOW))

    assert (data.total_today, data.completed_today, data.remaining_today) == (3, 1, 2)
    assert data.progress == 33
    assert data.next_reminder is not None
    assert data.next_reminder.medication_name == "Minoxidil"
    assert (data.next_reminder.minutes_until, data.next_reminder.is_tomorrow) == (0, False)
    assert data.current_streak == 2  # today still open, so the two finished days count
    assert len(data.heatmap) == 133
    today = data.heatmap[-1]
    assert (today.date, today.total, today.completed) == (TODAY, 3, 1)
    assert [m.name for m in data.medications] == ["Biotin", "Minoxidil", "Weekend"]  # enabled only


def test_dashboard_progress_rounds_half_up_like_javascript():
    meds = FakeMedications([med_doc(USER, f"M{i}", ["8:00 AM"]) for i in range(8)])
    logs = FakeDailyLogs()
    logs.add_dose(USER, TODAY, "M0", "8:00 AM")
    data = run(DashboardService(ScheduleService(meds, logs)).get(USER, NOW))
    assert data.progress == 13  # 1/8 = 12.5%; Python's round() would give 12


def test_medications_page_history_and_today(world):
    meds, logs, schedule = world
    data = run(MedicationService(meds, logs, schedule, FakeActivity()).page_data(USER, NOW))

    by_name = {m.name: m for m in data.medications}
    assert list(by_name) == ["Biotin", "Minoxidil", "Paused", "Weekend"]  # includes paused
    assert by_name["Paused"].enabled is False

    biotin = by_name["Biotin"]
    assert (biotin.total_today, biotin.completed_today) == (2, 1)
    assert [(d.time, d.completed) for d in biotin.today_doses] == [
        ("8:00 AM", True),
        ("8:00 PM", False),
    ]
    assert len(biotin.history) == 14
    assert biotin.history[-1].date == TODAY
    assert (biotin.history[-1].total, biotin.history[-1].completed) == (2, 1)
    assert biotin.history[-1].ratio == 0.5

    assert by_name["Weekend"].today_doses == []  # not due on a Wednesday
    assert by_name["Minoxidil"].today_doses[0].completed is False


def test_medication_create_normalizes_and_rejects_duplicates(world):
    meds, logs, schedule = world
    service = MedicationService(meds, logs, schedule, FakeActivity())
    body = MedicationInput(
        name="Vitamin D",
        schedule_times=["14:00", "2:00 PM", "08:05"],
        days_of_week=[5, 1, 1, 3],
    )
    created = run(service.create(USER, body))
    assert created.schedule_times == ["8:05 AM", "2:00 PM"]  # normalized, de-duplicated, sorted
    assert created.days_of_week == [1, 3, 5]
    assert created.enabled is True

    with pytest.raises(ConflictError, match="already exists"):
        run(service.create(USER, body))


def test_medication_update_toggle_delete_and_not_found(world):
    meds, logs, schedule = world
    service = MedicationService(meds, logs, schedule, FakeActivity())
    biotin = next(d for d in meds.docs if d["name"] == "Biotin")

    off = run(service.set_enabled(USER, biotin["_id"], False))
    assert off.enabled is False

    body = MedicationInput(name="Biotin Plus", schedule_times=["9:00 AM"], days_of_week=[0, 1])
    assert run(service.update(USER, biotin["_id"], body)).name == "Biotin Plus"

    with pytest.raises(NotFoundError):
        run(service.update("someone-else", biotin["_id"], body))  # not this user's medication
    with pytest.raises(NotFoundError):
        run(service.set_enabled(USER, "missing", True))
    run(service.delete(USER, biotin["_id"]))
    with pytest.raises(NotFoundError):
        run(service.delete(USER, biotin["_id"]))


def test_dose_completion_normalizes_time_and_defaults_date(world):
    _, logs, _ = world
    service = DoseService(logs)
    run(
        service.set_completion(
            USER,
            DoseCompletionInput(
                medication_name="Minoxidil", scheduled_time="10:00", completed=True, date=TODAY
            ),
        )
    )
    assert run(logs.is_dose_completed(USER, TODAY, "Minoxidil", "10:00 AM"))

    run(
        service.set_completion(
            USER,
            DoseCompletionInput(
                medication_name="Minoxidil", scheduled_time="10:00", completed=False, date=TODAY
            ),
        )
    )
    assert not run(logs.is_dose_completed(USER, TODAY, "Minoxidil", "10:00 AM"))


def test_statistics_rounding_missed_and_ordering():
    meds = FakeMedications([])
    logs = FakeDailyLogs()
    for i in range(8):  # 8 doses yesterday, only the first taken: 12.5%
        logs.add_dose(USER, "2026-01-06", f"M{i}", "8:00 AM", completed=(i == 0))
    schedule = ScheduleService(meds, logs)

    data = run(StatisticsService(logs, schedule).get(USER, NOW))

    assert (data.overall_completed, data.overall_total, data.overall_percent) == (1, 8, 13)
    assert (data.month_completed, data.month_total, data.month_percent) == (1, 8, 13)
    assert data.missed_reminders == 7
    assert [s.name for s in data.medication_stats][:3] == ["M0", "M1", "M2"]  # 100% first, then A-Z
    assert data.medication_stats[0].percent == 100
    assert len(data.heatmap) == 120
    assert data.current_streak == 0
    assert data.longest_streak == 0


def test_statistics_streaks():
    logs = FakeDailyLogs()
    for day in ("2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06"):
        logs.add_dose(USER, day, "A", "8:00 AM")
    logs.add_dose(USER, "2026-01-01", "A", "8:00 AM")
    schedule = ScheduleService(FakeMedications([]), logs)
    data = run(StatisticsService(logs, schedule).get(USER, NOW))
    assert data.longest_streak == 4
    assert data.current_streak == 4  # today is open, so it counts back from yesterday


def test_wellness_counter_notes_and_streaks():
    logs = FakeDailyLogs()
    service = WellnessService(logs)

    assert run(service.decrement(USER, "2026-01-05")) == 0  # never below zero
    assert run(service.increment(USER, "2026-01-05")) == 1
    assert run(service.increment(USER, "2026-01-05")) == 2
    assert run(service.increment(USER, TODAY)) == 1
    run(service.set_notes(USER, "felt fine", TODAY))
    assert run(service.reset(USER, "2026-01-04")) == 0

    data = run(service.get(USER, NOW))
    assert (data.today_key, data.today_count, data.today_notes) == (TODAY, 1, "felt fine")
    assert (len(data.weekly), len(data.monthly), len(data.calendar)) == (7, 30, 119)
    assert (data.total_tracked, data.total_this_year) == (3, 3)
    assert data.average_per_week == 0.3  # 3 / 12 weeks = 0.25, rounded half up like Math.round
    assert [h.date for h in data.history] == [TODAY, "2026-01-05"]
    assert data.history[0].label == "Jan 7"
    assert data.current_clean_streak == 0
    assert data.longest_clean_streak == 1  # only Jan 6 sits between the two logged days
    assert data.weekly[-1].count == 1


def test_wellness_with_no_logs_counts_today_as_clean():
    data = run(WellnessService(FakeDailyLogs()).get(USER, NOW))
    assert (data.total_tracked, data.today_count, data.today_notes) == (0, 0, "")
    assert data.current_clean_streak == data.longest_clean_streak == 1
    assert data.history == []
