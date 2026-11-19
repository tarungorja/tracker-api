import math
from dataclasses import dataclass
from datetime import datetime

from bson import ObjectId

from app.core.config import Settings
from app.core.constants import (
    OTP_MAX_ATTEMPTS,
    OTP_RESEND_COOLDOWN,
    OTP_TTL,
    REFRESH_REUSE_GRACE,
    OtpPurpose,
)
from app.core.exceptions import (
    BadGatewayError,
    BadRequestError,
    ConflictError,
    NotFoundError,
    TooManyRequestsError,
    UnauthorizedError,
)
from app.core.security import (
    generate_otp,
    generate_refresh_token,
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

_SESSION_ENDED = "Your session has ended. Sign in again."


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
    """When the whole session ends (the refresh token's expiry, if there is one)."""
    user: UserView
    refresh_token: str | None = None
    access_expires_at: datetime | None = None
    """Set only with refresh tokens: the access token is not accepted after this."""


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

    async def verify_otp(
        self, email: str, purpose: OtpPurpose, code: str, use_refresh_token: bool = False
    ) -> IssuedSession:
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

        return await self._start_session(str(user["_id"]), user["email"], use_refresh_token)

    async def _start_session(
        self, user_id: str, email: str, use_refresh_token: bool
    ) -> IssuedSession:
        moment = utcnow()
        token = generate_session_token()
        session_end = moment + self._settings.session_ttl
        user = UserView(id=user_id, email=email)

        if not use_refresh_token:  # one long-lived token, as before
            await self._sessions.create(hash_token(token), user_id, session_end)
            return IssuedSession(token, session_end, user)

        refresh_token = generate_refresh_token()
        access_end = min(moment + self._settings.access_token_ttl, session_end)
        await self._sessions.create(
            hash_token(token),
            user_id,
            session_end,
            access_expires_at=access_end,
            refresh_hash=hash_token(refresh_token),
        )
        return IssuedSession(token, session_end, user, refresh_token, access_end)

    async def refresh(self, refresh_token: str, now: datetime | None = None) -> IssuedSession:
        """Trades a refresh token for a new access + refresh pair (the old pair stops working).

        A refresh token works once. Replaying the one it replaced is treated as theft and ends the
        session, except within a few seconds, which is just two tabs refreshing at the same time.
        """
        moment = now or utcnow()
        old_hash = hash_token(refresh_token)
        token = generate_session_token()
        new_refresh = generate_refresh_token()
        session_end = moment + self._settings.session_ttl  # sliding: active users stay signed in
        access_end = moment + self._settings.access_token_ttl

        session = await self._sessions.rotate(
            old_hash, hash_token(token), hash_token(new_refresh), access_end, session_end, moment
        )
        if session is None:
            await self._reject_stale_refresh(old_hash, moment)  # always raises
            raise UnauthorizedError(_SESSION_ENDED)

        user = await self._users.find_by_id(session["userId"])
        if user is None:
            await self._revoke(session["_id"])
            raise UnauthorizedError(_SESSION_ENDED)
        return IssuedSession(
            token,
            session_end,
            UserView(id=str(user["_id"]), email=user["email"]),
            new_refresh,
            access_end,
        )

    async def _reject_stale_refresh(self, old_hash: str, moment: datetime) -> None:
        replaced = await self._sessions.find_by_previous_refresh_hash(old_hash)
        if replaced is not None:
            refreshed_at = replaced.get("refreshedAt")
            if refreshed_at is not None and moment - refreshed_at <= REFRESH_REUSE_GRACE:
                raise UnauthorizedError("Your session was just refreshed. Try again.")
            await self._revoke(replaced["_id"])  # an already-used token came back: assume theft
        raise UnauthorizedError(_SESSION_ENDED)

    async def _revoke(self, session_id: str | ObjectId) -> None:
        await self._sessions.delete_by_id(session_id)
        await self._push_tokens.delete_by_session(session_id)

    async def authenticate(self, token: str) -> AuthUser | None:
        session = await self._sessions.find_active_by_token_hash(hash_token(token))
        if session is None:
            return None
        user = await self._users.find_by_id(session["userId"])
        if user is None:
            return None
        return AuthUser(id=str(user["_id"]), email=user["email"], session_id=str(session["_id"]))

    async def sign_out(self, token: str | None, refresh_token: str | None = None) -> None:
        """Ends this device's session, found by its access token or else its refresh token."""
        session = await self._sessions.delete_by_token_hash(hash_token(token)) if token else None
        if session is None and refresh_token:
            session = await self._sessions.delete_by_refresh_hash(hash_token(refresh_token))
        # This device is signed out, so it must stop receiving this user's notifications.
        if session is not None:
            await self._push_tokens.delete_by_session(session["_id"])
