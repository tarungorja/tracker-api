import logging
from dataclasses import dataclass

from bson import ObjectId

from app.core.exceptions import BadGatewayError, ConflictError, ServiceUnavailableError
from app.db.repositories import PushTokenRepository, SessionRepository
from app.integrations.fcm import FcmClient
from app.schemas.push import PushTokenInput

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PushPayload:
    title: str
    body: str
    url: str = "/today"  # page opened when the notification is clicked
    tag: str = "reminder"  # notifications with the same tag replace each other


@dataclass(frozen=True)
class PushSendResult:
    sent: int
    failed: int
    error: str | None = None


class PushService:
    def __init__(
        self, push_tokens: PushTokenRepository, sessions: SessionRepository, fcm: FcmClient
    ) -> None:
        self._push_tokens = push_tokens
        self._sessions = sessions
        self._fcm = fcm

    async def save_token(self, user_id: str, session_id: str, data: PushTokenInput) -> None:
        """Registers this browser's token for the user (reassigning it if it was another user's)."""
        await self._push_tokens.upsert(data.token, user_id, session_id, data.user_agent or "")

    async def remove_token(self, user_id: str, token: str) -> None:
        await self._push_tokens.delete_for_user(token, user_id)

    async def send_to_user(self, user_id: str | ObjectId, payload: PushPayload) -> PushSendResult:
        """Sends a web push to every browser still signed in as this user."""
        session_ids = await self._sessions.active_ids_for_user(user_id)
        await self._push_tokens.delete_orphaned(user_id, session_ids)
        tokens = await self._push_tokens.tokens_for_user(user_id, session_ids)
        if not tokens:
            return PushSendResult(sent=0, failed=0)

        outcomes = await self._fcm.send_many(
            tokens,
            {"title": payload.title, "body": payload.body, "url": payload.url, "tag": payload.tag},
        )
        dead = [o.token for o in outcomes if o.dead]
        if dead:
            await self._push_tokens.delete_by_tokens(dead)

        sent = sum(1 for o in outcomes if o.ok)
        first_error = next((o.error for o in outcomes if not o.ok and o.error), None)
        return PushSendResult(sent=sent, failed=len(tokens) - sent, error=first_error)

    async def send_test(self, user_id: str) -> int:
        if not self._fcm.configured:
            raise ServiceUnavailableError(
                "Push sending isn't configured on the server yet (FIREBASE_SERVICE_ACCOUNT)."
            )
        try:
            result = await self.send_to_user(
                user_id,
                PushPayload(
                    title="Test notification",
                    body="Reminders are working. You'll be notified when it's time for a dose.",
                    tag="test",
                ),
            )
        except Exception as exc:
            logger.exception("Test notification failed")
            raise BadGatewayError(f"Could not send the test notification: {exc}") from exc

        if result.sent == 0:
            if result.error:
                raise BadGatewayError(f"Firebase could not deliver it: {result.error}")
            raise ConflictError(
                "No device is registered for this account. Turn reminders off and on again."
            )
        return result.sent
