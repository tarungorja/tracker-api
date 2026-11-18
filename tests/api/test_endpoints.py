"""Full HTTP round-trips (routing, validation, JSON shape, cookies) with in-memory repositories."""

import pytest
from fastapi.testclient import TestClient

from app import dependencies as deps
from app.core.config import get_settings
from app.main import create_app
from app.services.account_service import AccountService
from app.services.auth_service import AuthService, AuthUser
from app.services.dashboard_service import DashboardService
from app.services.dose_service import DoseService
from app.services.medication_service import MedicationService
from app.services.reminder_service import ReminderService
from app.services.schedule_service import ScheduleService
from app.services.statistics_service import StatisticsService
from app.services.today_service import TodayService
from app.services.wellness_service import WellnessService
from tests.fakes import (
    FakeDailyLogs,
    FakeEmail,
    FakeMedications,
    FakeOtps,
    FakePush,
    FakePushTokens,
    FakeRemindersSent,
    FakeSessions,
    FakeUsers,
    med_doc,
)

ME = AuthUser(id="u1", email="me@example.com", session_id="s1")


class StubPushService:
    """What the /push endpoints need, without Firebase."""

    def __init__(self) -> None:
        self.saved: list[tuple[str, str, str]] = []
        self.removed: list[tuple[str, str]] = []

    async def save_token(self, user_id, session_id, data):
        self.saved.append((user_id, session_id, data.token))

    async def remove_token(self, user_id, token):
        self.removed.append((user_id, token))

    async def send_test(self, user_id):
        return 2


class World:
    def __init__(self) -> None:
        self.meds = FakeMedications([med_doc("u1", "Biotin", ["8:00 AM", "8:00 PM"])])
        self.logs = FakeDailyLogs()
        self.schedule = ScheduleService(self.meds, self.logs)
        self.users, self.sessions, self.email = FakeUsers(), FakeSessions(), FakeEmail()
        self.otps = FakeOtps()
        self.account_tokens = FakePushTokens(["u1"])
        self.reminders_sent = FakeRemindersSent()
        self.auth = AuthService(
            self.users,
            self.otps,
            self.sessions,
            FakePushTokens(),
            self.email,
            get_settings(),
        )
        self.push = StubPushService()
        self.reminder = ReminderService(
            FakePushTokens([]), self.meds, self.logs, FakeRemindersSent(), FakePush()
        )

    def install(self, app, signed_in: bool) -> None:
        o = app.dependency_overrides
        o[deps.get_auth_service] = lambda: self.auth
        o[deps.get_medication_service] = lambda: MedicationService(
            self.meds, self.logs, self.schedule
        )
        o[deps.get_dose_service] = lambda: DoseService(self.logs)
        o[deps.get_today_service] = lambda: TodayService(self.schedule)
        o[deps.get_dashboard_service] = lambda: DashboardService(self.schedule)
        o[deps.get_statistics_service] = lambda: StatisticsService(self.logs, self.schedule)
        o[deps.get_wellness_service] = lambda: WellnessService(self.logs)
        o[deps.get_account_service] = lambda: AccountService(
            self.users,
            self.sessions,
            self.otps,
            self.account_tokens,
            self.meds,
            self.logs,
            self.reminders_sent,
        )
        o[deps.get_push_service] = lambda: self.push
        o[deps.get_reminder_service] = lambda: self.reminder
        if signed_in:
            o[deps.get_current_user] = lambda: ME


@pytest.fixture
def world():
    return World()


@pytest.fixture
def api(world):
    """A signed-in client."""
    app = create_app()
    world.install(app, signed_in=True)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def anon(world):
    """A client that must authenticate through the real session flow."""
    app = create_app()
    world.install(app, signed_in=False)
    with TestClient(app) as client:
        yield client


# ---- pages ---------------------------------------------------------------------------------


def test_page_endpoints_return_camel_case_json(api):
    today = api.get("/api/v1/today").json()
    assert {"todayKey", "nowMinutes", "slots", "total", "completed"} <= set(today)
    assert today["total"] == 2
    dose = today["slots"][0]["doses"][0]
    assert {"medicationName", "scheduledTime", "scheduledMinutes", "completedAt", "status"} <= set(
        dose
    )

    dash = api.get("/api/v1/dashboard").json()
    assert {
        "totalToday",
        "completedToday",
        "remainingToday",
        "currentStreak",
        "nextReminder",
    } <= set(dash)
    assert len(dash["heatmap"]) == 133

    stats = api.get("/api/v1/statistics").json()
    assert {"overallPercent", "longestStreak", "missedReminders", "medicationStats"} <= set(stats)

    wellness = api.get("/api/v1/wellness").json()
    assert {"todayCount", "totalThisYear", "averagePerWeek", "currentCleanStreak"} <= set(wellness)

    meds = api.get("/api/v1/medications").json()
    med = meds["medications"][0]
    assert {"scheduleTimes", "daysOfWeek", "todayDoses", "completedToday", "history"} <= set(med)


# ---- medications ---------------------------------------------------------------------------


def test_medication_crud_over_http(api):
    body = {"name": "Vitamin D", "scheduleTimes": ["14:00"], "daysOfWeek": [1, 3]}
    created = api.post("/api/v1/medications", json=body)
    assert created.status_code == 201
    med = created.json()
    assert (med["scheduleTimes"], med["daysOfWeek"], med["enabled"]) == (["2:00 PM"], [1, 3], True)

    dup = api.post("/api/v1/medications", json=body)
    assert dup.status_code == 409
    assert dup.json() == {"ok": False, "error": "A medication with that name already exists."}

    mid = med["id"]
    updated = api.put(f"/api/v1/medications/{mid}", json={**body, "name": "Vitamin D3"})
    assert updated.status_code == 200 and updated.json()["name"] == "Vitamin D3"

    toggled = api.patch(f"/api/v1/medications/{mid}/enabled", json={"enabled": False})
    assert toggled.json()["enabled"] is False

    assert api.delete(f"/api/v1/medications/{mid}").json() == {"ok": True}
    missing = api.delete(f"/api/v1/medications/{mid}")
    assert missing.status_code == 404
    assert missing.json() == {"ok": False, "error": "Medication not found."}


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"name": "", "scheduleTimes": ["8:00 AM"], "daysOfWeek": [1]}, "Name is required."),
        ({"name": "x", "scheduleTimes": [], "daysOfWeek": [1]}, "Add at least one time."),
        ({"name": "x", "scheduleTimes": ["soon"], "daysOfWeek": [1]}, "Enter a valid time."),
        (
            {"name": "x", "scheduleTimes": ["8:00 AM"], "daysOfWeek": []},
            "Pick at least one day of the week.",
        ),
    ],
)
def test_medication_validation_messages_reach_the_client(api, payload, message):
    response = api.post("/api/v1/medications", json=payload)
    assert response.status_code == 422
    assert response.json()["error"] == message


def test_malformed_medication_id_is_rejected(api):
    response = api.delete("/api/v1/medications/not-an-id")
    assert response.status_code == 422


# ---- doses & wellness ----------------------------------------------------------------------


def test_dose_completion_round_trip(api, world):
    ok = api.put(
        "/api/v1/doses/completion",
        json={
            "medicationName": "Biotin",
            "scheduledTime": "08:00",
            "completed": True,
            "date": "2026-01-07",
        },
    )
    assert ok.json() == {"ok": True}
    assert any(r["scheduledTime"] == "8:00 AM" and r["completed"] for r in world.logs.rows)

    bad = api.put(
        "/api/v1/doses/completion",
        json={
            "medicationName": "Biotin",
            "scheduledTime": "8:00 AM",
            "completed": True,
            "date": "2026-02-30",
        },
    )
    assert bad.status_code == 422 and bad.json()["error"] == "Invalid date."


def test_wellness_counter_endpoints(api):
    inc = api.post("/api/v1/wellness/count/increment", params={"date": "2026-01-05"})
    assert inc.json() == {"ok": True, "count": 1}
    assert (
        api.post("/api/v1/wellness/count/increment", params={"date": "2026-01-05"}).json()["count"]
        == 2
    )
    assert (
        api.post("/api/v1/wellness/count/decrement", params={"date": "2026-01-05"}).json()["count"]
        == 1
    )
    assert api.post("/api/v1/wellness/count/reset", params={"date": "2026-01-05"}).json() == {
        "ok": True,
        "count": 0,
    }
    assert (
        api.post("/api/v1/wellness/count/decrement", params={"date": "2026-01-05"}).json()["count"]
        == 0
    )
    assert api.post("/api/v1/wellness/count/increment").json()["count"] == 1  # defaults to today

    bad = api.post("/api/v1/wellness/count/increment", params={"date": "yesterday"})
    assert bad.status_code == 422 and bad.json()["error"] == "Invalid date."


def test_wellness_notes(api):
    assert api.put("/api/v1/wellness/notes", json={"notes": "ok"}).json() == {"ok": True}
    too_long = api.put("/api/v1/wellness/notes", json={"notes": "x" * 1001})
    assert too_long.status_code == 422 and too_long.json()["error"] == "Invalid note."


# ---- push & cron ---------------------------------------------------------------------------


def test_push_endpoints(api, world):
    token = "t" * 40
    assert api.post("/api/v1/push/tokens", json={"token": token}).json() == {"ok": True}
    assert world.push.saved == [("u1", "s1", token)]  # tied to the caller's session

    assert api.request("DELETE", "/api/v1/push/tokens", json={"token": token}).json() == {
        "ok": True
    }
    assert world.push.removed == [("u1", token)]

    assert api.post("/api/v1/push/test").json() == {"ok": True, "sent": 2}

    short = api.post("/api/v1/push/tokens", json={"token": "short"})
    assert short.status_code == 422


def test_cron_runs_with_secret_for_get_and_post(api):
    headers = {"Authorization": "Bearer cron-test-secret"}
    for method in ("GET", "POST"):
        response = api.request(method, "/api/v1/cron/send-reminders", headers=headers)
        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "usersChecked": 0,
            "dosesDue": 0,
            "notificationsSent": 0,
            "failures": 0,
        }
    assert api.get("/api/v1/cron/send-reminders").status_code == 401


# ---- auth: cookies and sessions ------------------------------------------------------------


def test_full_sign_up_sign_out_cycle_with_cookies(anon, world):
    assert anon.get("/api/v1/auth/me").status_code == 401

    assert anon.post(
        "/api/v1/auth/otp/request", json={"email": " Me@Example.com ", "purpose": "signup"}
    ).json() == {"ok": True}
    to, code, _ = world.email.sent[-1]
    assert to == "me@example.com"  # trimmed + lower-cased

    verify = anon.post(
        "/api/v1/auth/otp/verify",
        json={"email": "me@example.com", "purpose": "signup", "code": code},
    )
    assert verify.status_code == 200
    body = verify.json()
    assert body["ok"] is True and body["user"]["email"] == "me@example.com" and body["token"]

    cookie = verify.headers["set-cookie"]
    assert cookie.startswith(f"session={body['token']}")
    assert "HttpOnly" in cookie and "Path=/" in cookie and "SameSite=lax" in cookie
    assert "expires=" in cookie.lower()

    me = anon.get("/api/v1/auth/me")  # the cookie jar now carries the session
    assert me.status_code == 200 and me.json()["email"] == "me@example.com"

    bearer = TestClient(anon.app).get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['token']}"}
    )
    assert bearer.status_code == 200  # non-browser clients can use the token header

    out = anon.post("/api/v1/auth/signout")
    assert out.json() == {"ok": True}
    assert 'session=""' in out.headers["set-cookie"] or "Max-Age=0" in out.headers["set-cookie"]
    assert anon.get("/api/v1/auth/me").status_code == 401


def test_auth_errors_have_the_expected_status_and_message(anon, world):
    unknown = anon.post("/api/v1/auth/otp/request", json={"email": "a@b.co", "purpose": "signin"})
    assert unknown.status_code == 404
    assert unknown.json()["error"] == "No account found for this email. Sign up first."

    anon.post("/api/v1/auth/otp/request", json={"email": "a@b.co", "purpose": "signup"})
    again = anon.post("/api/v1/auth/otp/request", json={"email": "a@b.co", "purpose": "signup"})
    assert again.status_code == 429

    wrong = anon.post(
        "/api/v1/auth/otp/verify", json={"email": "a@b.co", "purpose": "signup", "code": "000000"}
    )
    assert wrong.status_code in (400, 200)  # 200 only if the random code happened to be 000000

    malformed = anon.post(
        "/api/v1/auth/otp/verify", json={"email": "a@b.co", "purpose": "signup", "code": "12"}
    )
    assert malformed.status_code == 422
    assert malformed.json()["error"] == "Enter the 6-digit code."


def test_signout_without_a_session_is_harmless(anon):
    assert anon.post("/api/v1/auth/signout").json() == {"ok": True}


def test_delete_account_erases_all_user_data_and_signs_out(anon, world):
    anon.post("/api/v1/auth/otp/request", json={"email": "me@example.com", "purpose": "signup"})
    code = world.email.sent[-1][1]
    verify = anon.post(
        "/api/v1/auth/otp/verify",
        json={"email": "me@example.com", "purpose": "signup", "code": code},
    )
    user_id = verify.json()["user"]["id"]

    # Data owned by this user, plus another user's data that must survive.
    world.meds.docs.append(med_doc(user_id, "Minoxidil", ["8:00 AM"]))
    world.logs.add_dose(user_id, "2026-01-01", "Minoxidil", "8:00 AM")
    world.logs.add_dose("someone-else", "2026-01-01", "Biotin", "8:00 AM")
    world.account_tokens.user_ids.append(user_id)

    out = anon.delete("/api/v1/auth/me")
    assert out.status_code == 200 and out.json() == {"ok": True}
    assert 'session=""' in out.headers["set-cookie"] or "Max-Age=0" in out.headers["set-cookie"]

    assert not [d for d in world.meds.docs if d["userId"] == user_id]
    assert [r["userId"] for r in world.logs.rows] == ["someone-else"]
    assert user_id not in world.account_tokens.user_ids
    assert "u1" in world.account_tokens.user_ids  # untouched
    assert "me@example.com" not in world.users.docs
    assert world.sessions.docs == []
    assert anon.get("/api/v1/auth/me").status_code == 401  # the old session is dead


def test_delete_account_requires_a_session(anon):
    assert anon.delete("/api/v1/auth/me").status_code == 401
