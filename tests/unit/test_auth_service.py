"""OTP sign-up / sign-in / session flows against in-memory repositories."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import Settings
from app.core.exceptions import (
    BadGatewayError,
    BadRequestError,
    ConflictError,
    NotFoundError,
    TooManyRequestsError,
)
from app.core.security import hash_token
from app.services.auth_service import AuthService
from tests.fakes import FakeEmail, FakeOtps, FakePushTokens, FakeSessions, FakeUsers

EMAIL = "tarun@example.com"


def run(coro):
    return asyncio.run(coro)


def make(fail_email: bool = False):
    settings = Settings(_env_file=None, mongodb_uri="mongodb://x/y", auth_secret="unit-test-secret")
    users, otps, sessions, push = FakeUsers(), FakeOtps(), FakeSessions(), FakePushTokens()
    email = FakeEmail(fail=fail_email)
    service = AuthService(users, otps, sessions, push, email, settings)
    return service, users, otps, sessions, push, email


def test_signup_flow_creates_user_and_session():
    service, users, otps, sessions, _, email = make()

    run(service.request_otp(EMAIL, "signup"))
    to, code, purpose = email.sent[-1]
    assert (to, purpose) == (EMAIL, "signup")
    assert len(code) == 6 and code.isdigit()
    stored = otps.docs[(EMAIL, "signup")]
    assert code not in stored["codeHash"]  # only an HMAC of the code is stored

    issued = run(service.verify_otp(EMAIL, "signup", code))
    assert issued.user.email == EMAIL
    assert EMAIL in users.docs
    assert (EMAIL, "signup") not in otps.docs  # single use
    assert sessions.docs[0]["tokenHash"] == hash_token(issued.token)  # only the hash is stored
    assert issued.token not in str(sessions.docs)
    assert issued.expires_at > datetime.now(UTC) + timedelta(days=29)

    user = run(service.authenticate(issued.token))
    assert user is not None and user.email == EMAIL
    assert run(service.authenticate("not-a-real-token")) is None


def test_sign_out_revokes_session_and_push_tokens():
    service, _, _, sessions, push, email = make()
    run(service.request_otp(EMAIL, "signup"))
    issued = run(service.verify_otp(EMAIL, "signup", email.sent[-1][1]))
    session_id = sessions.docs[0]["_id"]

    run(service.sign_out(issued.token))
    assert run(service.authenticate(issued.token)) is None
    assert push.deleted_sessions == [session_id]
    run(service.sign_out(issued.token))  # signing out twice is harmless


def test_signin_flow_for_existing_user():
    service, users, _, _, _, email = make()
    run(users.create(EMAIL))
    run(service.request_otp(EMAIL, "signin"))
    issued = run(service.verify_otp(EMAIL, "signin", email.sent[-1][1]))
    assert issued.user.email == EMAIL
    assert len(users.docs) == 1  # signing in never creates another account


def test_purpose_must_match_account_state():
    service, users, *_ = make()
    with pytest.raises(NotFoundError, match="Sign up first"):
        run(service.request_otp(EMAIL, "signin"))
    run(users.create(EMAIL))
    with pytest.raises(ConflictError, match="already exists"):
        run(service.request_otp(EMAIL, "signup"))


def test_resend_cooldown():
    service, *_ = make()
    run(service.request_otp(EMAIL, "signup"))
    with pytest.raises(TooManyRequestsError, match=r"Please wait \d+s"):
        run(service.request_otp(EMAIL, "signup"))


def test_wrong_codes_lock_out_after_five_attempts():
    service, _, otps, _, _, email = make()
    run(service.request_otp(EMAIL, "signup"))
    good = email.sent[-1][1]
    bad = "000000" if good != "000000" else "111111"

    for _ in range(4):
        with pytest.raises(BadRequestError, match="Incorrect code"):
            run(service.verify_otp(EMAIL, "signup", bad))
    assert otps.docs[(EMAIL, "signup")]["attempts"] == 4

    with pytest.raises(TooManyRequestsError, match="Too many incorrect attempts"):
        run(service.verify_otp(EMAIL, "signup", bad))
    assert (EMAIL, "signup") not in otps.docs

    with pytest.raises(BadRequestError, match="expired"):  # even the right code is now dead
        run(service.verify_otp(EMAIL, "signup", good))


def test_expired_code_is_rejected_and_removed():
    service, _, otps, _, _, email = make()
    run(service.request_otp(EMAIL, "signup"))
    otps.docs[(EMAIL, "signup")]["expiresAt"] = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(BadRequestError, match="expired"):
        run(service.verify_otp(EMAIL, "signup", email.sent[-1][1]))
    assert (EMAIL, "signup") not in otps.docs


def test_code_cannot_be_reused():
    service, _, _, _, _, email = make()
    run(service.request_otp(EMAIL, "signup"))
    code = email.sent[-1][1]
    run(service.verify_otp(EMAIL, "signup", code))
    with pytest.raises(BadRequestError, match="expired"):
        run(service.verify_otp(EMAIL, "signup", code))


def test_code_for_one_email_does_not_verify_another():
    service, _, _, _, _, email = make()
    run(service.request_otp(EMAIL, "signup"))
    code = email.sent[-1][1]
    with pytest.raises(BadRequestError, match="expired"):  # no OTP exists for that address
        run(service.verify_otp("other@example.com", "signup", code))


def test_email_failure_leaves_no_usable_code_or_cooldown():
    service, _, otps, *_ = make(fail_email=True)
    with pytest.raises(BadGatewayError, match="Email provider error"):
        run(service.request_otp(EMAIL, "signup"))
    assert (EMAIL, "signup") not in otps.docs


def test_the_fifth_attempt_can_still_succeed():
    service, _, _, _, _, email = make()
    run(service.request_otp(EMAIL, "signup"))
    good = email.sent[-1][1]
    bad = "000000" if good != "000000" else "111111"
    for _ in range(4):
        with pytest.raises(BadRequestError, match="Incorrect code"):
            run(service.verify_otp(EMAIL, "signup", bad))
    assert run(service.verify_otp(EMAIL, "signup", good)).user.email == EMAIL


def test_attempts_are_counted_even_when_the_guess_is_right_after_lockout():
    service, _, otps, _, _, email = make()
    run(service.request_otp(EMAIL, "signup"))
    good = email.sent[-1][1]
    # Simulate parallel guesses having already used up every attempt (counter past the limit).
    otps.docs[(EMAIL, "signup")]["attempts"] = 5
    with pytest.raises(TooManyRequestsError):
        run(service.verify_otp(EMAIL, "signup", good))  # the correct code is no longer accepted
    assert (EMAIL, "signup") not in otps.docs
