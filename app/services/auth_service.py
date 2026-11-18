import math
from dataclasses import dataclass
from datetime import datetime

from app.core.config import Settings
from app.core.constants import (
    OTP_MAX_ATTEMPTS,
    OTP_RESEND_COOLDOWN,
    OTP_TTL,
    OtpPurpose,
)
from app.core.exceptions import (
    BadGatewayError,
    BadRequestError,
    ConflictError,
    NotFoundError,
    TooManyRequestsError,
)
from app.core.security import (
    generate_otp,
    generate_session_token,
    hash_otp,
    hash_token,
    verify_otp_hash,
)
from app.db.base import DuplicateKeyError
from app.db.repositories import (
    OtpRepository,
    PushTokenRepository,
    SessionRepository,
    UserRepository,
)
from app.integrations.email import BrevoEmailClient, EmailDeliveryError
from app.schemas.auth import UserView
from app.utils.time import utcnow


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str
    session_id: str
    """The login session of this browser/device."""


@dataclass(frozen=True)
class IssuedSession:
    token: str
    expires_at: datetime
    user: UserView


class AuthService:
    def __init__(
        self,
        users: UserRepository,
        otps: OtpRepository,
        sessions: SessionRepository,
        push_tokens: PushTokenRepository,
        email: BrevoEmailClient,
        settings: Settings,
    ) -> None:
        self._users = users
        self._otps = otps
        self._sessions = sessions
        self._push_tokens = push_tokens
        self._email = email
        self._settings = settings

    async def request_otp(self, email: str, purpose: OtpPurpose) -> None:
        user_exists = await self._users.exists_by_email(email)
        if purpose == "signup" and user_exists:
            raise ConflictError("An account with this email already exists. Sign in instead.")
        if purpose == "signin" and not user_exists:
            raise NotFoundError("No account found for this email. Sign up first.")

        now = utcnow()
        existing = await self._otps.find(email, purpose)
        if existing:
            wait = (existing["sentAt"] + OTP_RESEND_COOLDOWN - now).total_seconds()
            if wait > 0:
                raise TooManyRequestsError(
                    f"Please wait {math.ceil(wait)}s before requesting another code."
                )

        code = generate_otp()
        await self._otps.upsert(
            email,
            purpose,
            hash_otp(self._settings.auth_secret, email, code),
            sent_at=now,
            expires_at=now + OTP_TTL,
        )

        try:
            await self._email.send_otp(email, code, purpose)
        except EmailDeliveryError as exc:
            # Don't leave an unusable code (and its cooldown) behind if delivery failed.
            await self._otps.delete(email, purpose)
            raise BadGatewayError(str(exc)) from exc

    async def verify_otp(self, email: str, purpose: OtpPurpose, code: str) -> IssuedSession:
        otp = await self._otps.find(email, purpose)
        if otp is None or otp["expiresAt"] <= utcnow():
            if otp is not None:
                await self._otps.delete_by_id(otp["_id"])
            raise BadRequestError("That code has expired. Request a new one.")

        # Count the attempt *before* checking the code, atomically: parallel guesses each get
        # their own number, so an attacker can't exceed OTP_MAX_ATTEMPTS by racing requests.
        attempts = await self._otps.increment_attempts(otp["_id"])
        if attempts is None:
            raise BadRequestError("That code has expired. Request a new one.")
        if attempts > OTP_MAX_ATTEMPTS:
            await self._otps.delete_by_id(otp["_id"])
            raise TooManyRequestsError("Too many incorrect attempts. Request a new code.")

        if not verify_otp_hash(self._settings.auth_secret, email, code, otp["codeHash"]):
            if attempts >= OTP_MAX_ATTEMPTS:
                await self._otps.delete_by_id(otp["_id"])
                raise TooManyRequestsError("Too many incorrect attempts. Request a new code.")
            raise BadRequestError("Incorrect code. Try again.")

        # Consume as soon as it's verified; if another request already did, stop.
        if not await self._otps.consume(otp["_id"]):
            raise ConflictError("That code has already been used.")

        if purpose == "signup":
            try:
                user = await self._users.create(email)
            except DuplicateKeyError as exc:
                raise ConflictError(
                    "An account with this email already exists. Sign in instead."
                ) from exc
        else:
            existing_user = await self._users.find_by_email(email)
            if existing_user is None:
                raise NotFoundError("No account found for this email.")
            user = existing_user

        user_id = str(user["_id"])
        token = generate_session_token()
        expires_at = utcnow() + self._settings.session_ttl
        await self._sessions.create(hash_token(token), user_id, expires_at)
        return IssuedSession(token, expires_at, UserView(id=user_id, email=user["email"]))

    async def authenticate(self, token: str) -> AuthUser | None:
        session = await self._sessions.find_active_by_token_hash(hash_token(token))
        if session is None:
            return None
        user = await self._users.find_by_id(session["userId"])
        if user is None:
            return None
        return AuthUser(id=str(user["_id"]), email=user["email"], session_id=str(session["_id"]))

    async def sign_out(self, token: str) -> None:
        session = await self._sessions.delete_by_token_hash(hash_token(token))
        # This device is signed out, so it must stop receiving this user's notifications.
        if session is not None:
            await self._push_tokens.delete_by_session(session["_id"])
