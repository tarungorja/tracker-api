"""Father/son linking, the read-only overview and missed-dose reminders."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.core.exceptions import (
    BadGatewayError,
    BadRequestError,
    ConflictError,
    NotFoundError,
    TooManyRequestsError,
)
from app.services.dashboard_service import DashboardService
from app.services.family_service import FamilyService, missed_doses
from app.services.push_service import PushSendResult
from app.services.schedule_service import ScheduleService
from tests.fakes import (
    FakeActivity,
    FakeDailyLogs,
    FakeInvites,
    FakeLinks,
    FakeMedications,
    FakePush,
    FakeUsers,
    med_doc,
)

# Wednesday 2026-01-07, 10:00 IST (04:30 UTC).
NOW = datetime(2026, 1, 7, 4, 30, tzinfo=UTC)
TODAY = "2026-01-07"
SON_EMAIL = "son@example.com"


def run(coro):
    return asyncio.run(coro)


class Setup:
    def __init__(self, push: FakePush | None = None) -> None:
        self.users = FakeUsers()
        self.father = run(self.users.create("dad@example.com"))["_id"]
        self.son = run(self.users.create(SON_EMAIL))["_id"]
        self.meds = FakeMedications(
            [
                med_doc(self.father, "Biotin", ["8:00 AM", "8:00 PM"]),  # 8 AM is missed at 10:00
                med_doc(self.father, "Minoxidil", ["10:00 AM"]),  # due exactly now: not missed yet
            ]
        )
        self.logs = FakeDailyLogs()
        self.activity = FakeActivity()
        self.links, self.invites = FakeLinks(), FakeInvites()
        self.push = push or FakePush()
        dashboard = DashboardService(ScheduleService(self.meds, self.logs))
        self.service = FamilyService(
            self.users, self.links, self.invites, self.activity, dashboard, self.push
        )

    def connect(self) -> None:
        invite = run(self.service.create_invite(self.father))
        run(self.service.connect(self.son, invite.code))

    def remind(self, now: datetime = NOW):
        return run(self.service.remind(self.son, SON_EMAIL, self.father, now))


def test_connect_with_code_is_single_use_and_forgiving_about_format():
    s = Setup()
    invite = run(s.service.create_invite(s.father))
    assert len(invite.code) == 9 and invite.code[4] == "-"

    linked = run(s.service.connect(s.son, invite.code.lower().replace("-", " ")))
    assert linked.email == "dad@example.com"
    assert [u.email for u in run(s.service.list_patients(s.son))] == ["dad@example.com"]
    assert [u.email for u in run(s.service.list_caregivers(s.father))] == [SON_EMAIL]

    with pytest.raises(BadRequestError):  # already used
        run(s.service.connect(s.son, invite.code))


def test_connect_rejects_bad_expired_and_own_codes():
    s = Setup()
    with pytest.raises(BadRequestError):
        run(s.service.connect(s.son, "nope"))
    with pytest.raises(BadRequestError):
        run(s.service.connect(s.son, "ABCD-EFGH"))

    invite = run(s.service.create_invite(s.father))
    with pytest.raises(BadRequestError, match="own account"):
        run(s.service.connect(s.father, invite.code))

    expired = run(s.service.create_invite(s.father, now=NOW - timedelta(days=3)))
    with pytest.raises(BadRequestError):
        run(s.service.connect(s.son, expired.code))


def test_new_invite_replaces_the_old_one():
    s = Setup()
    first = run(s.service.create_invite(s.father))
    run(s.service.create_invite(s.father))
    with pytest.raises(BadRequestError):
        run(s.service.connect(s.son, first.code))


def test_overview_requires_a_link_and_shows_missed_and_activity():
    s = Setup()
    with pytest.raises(NotFoundError):
        run(s.service.overview(s.son, s.father, NOW))

    s.connect()
    run(s.activity.record(s.father, "added", "Biotin"))
    view = run(s.service.overview(s.son, s.father, NOW))

    assert view.patient.email == "dad@example.com"
    assert [(d.medication_name, d.scheduled_time) for d in view.missed] == [("Biotin", "8:00 AM")]
    assert view.dashboard.total_today == 3
    assert [(a.action, a.medication_name) for a in view.activity] == [("added", "Biotin")]
    assert view.last_medication_update_at is not None
    assert view.remind_available_in_seconds == 0


def test_missed_excludes_taken_and_future_doses():
    s = Setup()
    s.logs.add_dose(s.father, TODAY, "Biotin", "8:00 AM", completed_at=NOW)
    doses = run(DashboardService(ScheduleService(s.meds, s.logs)).get(s.father, NOW)).doses
    assert missed_doses(doses, 600) == []


def test_remind_sends_only_for_missed_doses():
    s = Setup()
    s.connect()

    result = s.remind()
    assert (result.sent, result.missed_count) == (1, 1)
    user_id, payload = s.push.calls[0]
    assert user_id == s.father
    assert "Biotin (8:00 AM)" in payload.body and "Minoxidil" not in payload.body
    assert SON_EMAIL in payload.body


def test_remind_is_refused_when_nothing_was_missed():
    s = Setup()
    s.connect()
    s.logs.add_dose(s.father, TODAY, "Biotin", "8:00 AM", completed_at=NOW)

    with pytest.raises(ConflictError, match="Nothing has been missed"):
        s.remind()
    assert s.push.calls == []


def test_remind_requires_a_link():
    s = Setup()
    with pytest.raises(NotFoundError):
        s.remind()
    assert s.push.calls == []


def test_remind_has_a_cooldown_that_overview_reports():
    s = Setup()
    s.connect()
    s.remind()

    with pytest.raises(TooManyRequestsError):
        s.remind(NOW + timedelta(minutes=1))

    view = run(s.service.overview(s.son, s.father, NOW + timedelta(minutes=1)))
    assert 0 < view.remind_available_in_seconds <= 240

    later = NOW + timedelta(minutes=6)
    assert run(s.service.overview(s.son, s.father, later)).remind_available_in_seconds == 0
    assert s.remind(later).sent == 1


def test_failed_delivery_does_not_start_the_cooldown():
    s = Setup(FakePush(PushSendResult(sent=0, failed=0)))
    s.connect()
    with pytest.raises(ConflictError, match="notifications"):
        s.remind()

    s.push.result = PushSendResult(sent=0, failed=1, error="UNREGISTERED: gone")
    with pytest.raises(BadGatewayError):
        s.remind()

    s.push.result = PushSendResult(sent=1, failed=0)
    assert s.remind().sent == 1


def test_either_side_can_end_the_connection():
    s = Setup()
    s.connect()
    run(s.service.revoke_caregiver(s.father, s.son))
    with pytest.raises(NotFoundError):
        run(s.service.overview(s.son, s.father, NOW))

    s.connect()
    run(s.service.stop_following(s.son, s.father))
    assert run(s.service.list_patients(s.son)) == []
    with pytest.raises(NotFoundError):
        run(s.service.stop_following(s.son, s.father))
