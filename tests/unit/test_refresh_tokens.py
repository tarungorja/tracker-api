"""Short-lived access tokens + rotating refresh tokens, against in-memory repositories."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import Settings
from app.core.exceptions import UnauthorizedError
from app.core.security import hash_token
from app.services.auth_service import AuthService
from tests.fakes import FakeEmail, FakeOtps, FakePushTokens, FakeSessions, FakeUsers

EMAIL = "tarun@example.com"


def run(coro):
    return asyncio.run(coro)


class Setup:
    def __init__(self) -> None:
        settings = Settings(
            _env_file=None, mongodb_uri="mongodb://x/y", auth_secret="unit-test-secret"
        )
        self.users, self.sessions = FakeUsers(), FakeSessions()
        self.push, self.email = FakePushTokens(), FakeEmail()
        self.service = AuthService(
            self.users, FakeOtps(), self.sessions, self.push, self.email, settings
        )

    def sign_in(self, use_refresh_token: bool = True):
        if EMAIL not in self.users.docs:
            run(self.users.create(EMAIL))
        run(self.service.request_otp(EMAIL, "signin"))
        code = self.email.sent[-1][1]
        return run(self.service.verify_otp(EMAIL, "signin", code, use_refresh_token))


def test_sign_in_issues_a_short_access_token_and_a_refresh_token():
    s = Setup()
    issued = s.sign_in()

    assert issued.refresh_token and issued.refresh_token != issued.token
    assert issued.access_expires_at is not None
    assert issued.access_expires_at < datetime.now(UTC) + timedelta(minutes=16)
    assert issued.expires_at > datetime.now(UTC) + timedelta(days=29)  # the session itself
    stored = s.sessions.docs[0]
    assert stored["refreshHash"] == hash_token(issued.refresh_token)
    assert issued.refresh_token not in str(s.sessions.docs)  # only hashes are stored
    assert run(s.service.authenticate(issued.token)) is not None


def test_signing_in_without_the_opt_in_is_unchanged():
    s = Setup()
    issued = s.sign_in(use_refresh_token=False)
    assert issued.refresh_token is None and issued.access_expires_at is None
    assert "refreshHash" not in s.sessions.docs[0]
    assert run(s.service.authenticate(issued.token)) is not None


def test_access_token_stops_working_when_it_expires():
    s = Setup()
    issued = s.sign_in()
    s.sessions.docs[0]["accessExpiresAt"] = datetime.now(UTC) - timedelta(seconds=1)

    assert run(s.service.authenticate(issued.token)) is None  # needs a refresh
    assert run(s.service.refresh(issued.refresh_token)).token  # which still works


def test_refresh_rotates_both_tokens_and_keeps_the_same_session():
    s = Setup()
    first = s.sign_in()
    session_id = s.sessions.docs[0]["_id"]

    second = run(s.service.refresh(first.refresh_token))
    assert second.token != first.token and second.refresh_token != first.refresh_token
    assert second.user.email == EMAIL
    assert [d["_id"] for d in s.sessions.docs] == [session_id]  # same device, same session

    assert run(s.service.authenticate(first.token)) is None  # the old access token is dead
    assert run(s.service.authenticate(second.token)) is not None
    assert run(s.service.refresh(second.refresh_token)).refresh_token  # and it keeps going


def test_replaying_an_old_refresh_token_revokes_the_session():
    s = Setup()
    first = s.sign_in()
    session_id = s.sessions.docs[0]["_id"]
    t0 = datetime.now(UTC)
    second = run(s.service.refresh(first.refresh_token, t0))

    # Replayed moments later: two tabs racing. Rejected, but nothing is revoked.
    with pytest.raises(UnauthorizedError, match="just refreshed"):
        run(s.service.refresh(first.refresh_token, t0 + timedelta(seconds=3)))
    assert run(s.service.authenticate(second.token)) is not None

    # Replayed later: the old token was stolen. The whole session ends.
    with pytest.raises(UnauthorizedError, match="session has ended"):
        run(s.service.refresh(first.refresh_token, t0 + timedelta(minutes=5)))
    assert s.sessions.docs == []
    assert s.push.deleted_sessions == [session_id]
    assert run(s.service.authenticate(second.token)) is None
    with pytest.raises(UnauthorizedError):
        run(s.service.refresh(second.refresh_token, t0 + timedelta(minutes=6)))


def test_refresh_rejects_unknown_and_expired_tokens():
    s = Setup()
    with pytest.raises(UnauthorizedError):
        run(s.service.refresh("not-a-token"))

    issued = s.sign_in()
    s.sessions.docs[0]["expiresAt"] = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(UnauthorizedError):
        run(s.service.refresh(issued.refresh_token))


def test_refresh_for_a_deleted_account_ends_the_session():
    s = Setup()
    issued = s.sign_in()
    s.users.docs.clear()
    with pytest.raises(UnauthorizedError):
        run(s.service.refresh(issued.refresh_token))
    assert s.sessions.docs == []


def test_sign_out_works_with_only_the_refresh_token():
    s = Setup()
    issued = s.sign_in()
    session_id = s.sessions.docs[0]["_id"]
    s.sessions.docs[0]["accessExpiresAt"] = datetime.now(UTC) - timedelta(seconds=1)

    run(s.service.sign_out(None, issued.refresh_token))
    assert s.sessions.docs == [] and s.push.deleted_sessions == [session_id]
    with pytest.raises(UnauthorizedError):
        run(s.service.refresh(issued.refresh_token))
