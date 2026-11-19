"""The reminder job: due-dose detection, de-duplication and retry on delivery failure."""

import asyncio
from datetime import UTC, datetime

from app.services.push_service import PushSendResult
from app.services.reminder_service import ReminderService
from tests.fakes import (
    FakeDailyLogs,
    FakeMedications,
    FakePush,
    FakePushTokens,
    FakeRemindersSent,
    med_doc,
)

USER = "u1"
TODAY = "2026-01-07"  # a Wednesday
# 10:02 IST, two minutes after a 10:00 AM dose.
NOW = datetime(2026, 1, 7, 4, 32, tzinfo=UTC)


def run(coro):
    return asyncio.run(coro)


def build(meds, push=None, user_ids=(USER,)):
    logs = FakeDailyLogs()
    sent = FakeRemindersSent()
    push = push or FakePush()
    service = ReminderService(
        FakePushTokens(list(user_ids)), FakeMedications(meds), logs, sent, push
    )
    return service, logs, sent, push


def test_due_dose_is_notified_once_across_overlapping_runs():
    service, _, _, push = build([med_doc(USER, "Minoxidil", ["10:00 AM"])])

    first = run(service.send_due(NOW))
    assert (first.users_checked, first.doses_due, first.notifications_sent, first.failures) == (
        1,
        1,
        1,
        0,
    )
    user_id, payload = push.calls[0]
    assert user_id == USER
    assert payload.title == "Time for your 10:00 AM medication"
    assert payload.body == "Minoxidil"
    assert payload.tag == f"dose-{TODAY}-10:00 AM"

    second = run(service.send_due(NOW))  # another worker / the cron endpoint at the same time
    assert second.notifications_sent == 0
    assert len(push.calls) == 1


def test_doses_at_the_same_time_are_grouped_into_one_notification():
    service, _, _, push = build(
        [med_doc(USER, "Biotin", ["10:00 AM"]), med_doc(USER, "Minoxidil", ["10:00 AM"])]
    )
    result = run(service.send_due(NOW))
    assert result.doses_due == 2
    assert len(push.calls) == 1
    assert push.calls[0][1].body == "Biotin, Minoxidil"


def test_completed_disabled_wrong_day_and_out_of_window_doses_are_skipped():
    service, logs, _, push = build(
        [
            med_doc(USER, "Done", ["10:00 AM"]),
            med_doc(USER, "Paused", ["10:00 AM"], enabled=False),
            med_doc(USER, "Weekend", ["10:00 AM"], days=[0, 6]),
            med_doc(USER, "Earlier", ["9:00 AM"]),  # 62 minutes ago: outside the 5-minute window
            med_doc(USER, "Later", ["10:30 AM"]),
        ]
    )
    logs.add_dose(USER, TODAY, "Done", "10:00 AM", completed=True)

    result = run(service.send_due(NOW))
    assert push.calls == []
    assert result.notifications_sent == 0


def test_a_slightly_late_run_still_catches_the_dose():
    service, _, _, push = build([med_doc(USER, "Minoxidil", ["10:00 AM"])])
    late = datetime(2026, 1, 7, 4, 34, tzinfo=UTC)  # 10:04 IST, still inside the window
    assert run(service.send_due(late)).notifications_sent == 1
    too_late = datetime(2026, 1, 7, 4, 36, tzinfo=UTC)  # 10:06 IST
    assert (
        run(build([med_doc(USER, "Minoxidil", ["10:00 AM"])])[0].send_due(too_late)).doses_due == 0
    )
    assert len(push.calls) == 1


def test_failed_delivery_releases_the_claim_so_the_next_run_retries():
    push = FakePush(PushSendResult(sent=0, failed=1, error="boom"))
    service, _, sent, _ = build([med_doc(USER, "Minoxidil", ["10:00 AM"])], push=push)

    result = run(service.send_due(NOW))
    assert (result.notifications_sent, result.failures) == (0, 1)
    assert sent.claimed == set()  # released

    push.result = PushSendResult(sent=1, failed=0)
    assert run(service.send_due(NOW)).notifications_sent == 1


def test_user_with_no_registered_device_is_not_retried_forever():
    push = FakePush(PushSendResult(sent=0, failed=0))  # tokens pruned: nothing to deliver to
    service, _, sent, _ = build([med_doc(USER, "Minoxidil", ["10:00 AM"])], push=push)
    run(service.send_due(NOW))
    assert len(sent.claimed) == 1  # claim kept, matching the original behavior


def test_users_without_devices_are_not_checked():
    service, *_ = build([med_doc(USER, "Minoxidil", ["10:00 AM"])], user_ids=())
    result = run(service.send_due(NOW))
    assert (result.users_checked, result.doses_due) == (0, 0)


def test_an_exception_from_push_counts_as_a_failure_and_releases_the_claim():
    class Exploding(FakePush):
        async def send_to_user(self, user_id, payload):
            raise RuntimeError("fcm down")

    service, _, sent, _ = build([med_doc(USER, "Minoxidil", ["10:00 AM"])], push=Exploding())
    result = run(service.send_due(NOW))
    assert result.failures == 1
    assert sent.claimed == set()


def test_dose_reminders_leave_out_the_android_app_which_schedules_its_own():
    service, _, _, push = build([med_doc(USER, "Minoxidil", ["10:00 AM"])])
    run(service.send_due(NOW))
    assert push.include_native == [False]  # the push to the user skips native tokens
    assert service._push_tokens.distinct_calls == [False]  # and so does the user lookup
