"""Firebase Cloud Messaging (HTTP v1) web-push sender."""

import asyncio
import base64
import json
import re
import threading
from dataclasses import dataclass
from typing import Any

import httpx
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account

from app.core.tls import httpx_verify, requests_session

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
FCM_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
# Notification channel the Android app creates for dose reminders (src/lib/notifications).
ANDROID_CHANNEL_ID = "dose-reminders"


class FcmConfigError(Exception):
    """FIREBASE_SERVICE_ACCOUNT is missing or unreadable."""


@dataclass(frozen=True)
class SendOutcome:
    token: str
    ok: bool
    dead: bool = False  # Firebase says the token is gone and should be pruned
    error: str | None = None


def _try_parse(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


def parse_service_account(raw: str) -> dict[str, Any]:
    """Leniently reads FIREBASE_SERVICE_ACCOUNT.

    Accepts raw JSON, JSON wrapped in quotes, JSON whose private key contains real line
    breaks instead of "\\n", and base64-encoded JSON.
    """
    text = raw.strip()

    if len(text) > 1 and text[0] == text[-1] and text[0] in "'\"":
        unwrapped = _try_parse(text) if text[0] == '"' else None
        text = unwrapped if isinstance(unwrapped, str) else text[1:-1]

    if not text.startswith("{"):
        try:
            decoded = base64.b64decode(text).decode("utf-8").strip()
        except ValueError:
            decoded = ""
        if decoded.startswith("{"):
            text = decoded

    def escape_key_newlines(match: re.Match[str]) -> str:
        key = match.group(2).replace("\r\n", "\\n").replace("\n", "\\n")
        return f"{match.group(1)}{key}{match.group(3)}"

    candidates = [
        text,
        re.sub(r'("private_key"\s*:\s*")([\s\S]*?)("\s*[,}])', escape_key_newlines, text),
        text.replace('\\"', '"'),
    ]
    for candidate in candidates:
        value = _try_parse(candidate)
        if (
            isinstance(value, dict)
            and value.get("project_id")
            and value.get("client_email")
            and value.get("private_key")
        ):
            return value

    raise FcmConfigError(
        "FIREBASE_SERVICE_ACCOUNT could not be read as the service-account JSON. Paste the whole "
        "contents of the downloaded key file as the value (no extra quotes), "
        "or its base64 encoding."
    )


class FcmClient:
    def __init__(self, raw_service_account: str | None, use_system_ca: bool = False) -> None:
        self._raw = raw_service_account
        self._use_system_ca = use_system_ca
        self._credentials: service_account.Credentials | None = None
        self._project_id: str | None = None
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self._raw)

    def _access_token(self) -> tuple[str, str]:
        """Blocking: returns (project_id, bearer token). Run in a worker thread."""
        if not self._raw:
            raise FcmConfigError(
                "Missing FIREBASE_SERVICE_ACCOUNT. Generate a private key in Firebase console > "
                "Project settings > Service accounts and add the JSON to your environment."
            )
        with self._lock:
            if self._credentials is None:
                info = parse_service_account(self._raw)
                info["private_key"] = info["private_key"].replace("\\n", "\n")
                self._credentials = service_account.Credentials.from_service_account_info(
                    info, scopes=[FCM_SCOPE]
                )
                self._project_id = info["project_id"]
            if not self._credentials.valid:
                self._credentials.refresh(
                    GoogleRequest(session=requests_session(self._use_system_ca))
                )
            assert self._project_id is not None and self._credentials.token is not None
            return self._project_id, self._credentials.token

    async def send_many(self, tokens: list[str], data: dict[str, str]) -> list[SendOutcome]:
        """Sends one message per token.

        Browsers get the data and build the notification in the service worker. The native Android
        app ignores data-only messages while open and drops their body in the background, so the
        message also carries an `android.notification` block that the OS and expo-notifications
        display; FCM applies it to Android registrations only.
        """
        if not tokens:
            return []
        project_id, access_token = await asyncio.to_thread(self._access_token)
        url = FCM_URL.format(project_id=project_id)
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(
            timeout=15, verify=httpx_verify(self._use_system_ca)
        ) as client:
            return list(
                await asyncio.gather(
                    *(self._send_one(client, url, headers, token, data) for token in tokens)
                )
            )

    @staticmethod
    async def _send_one(
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        token: str,
        data: dict[str, str],
    ) -> SendOutcome:
        body = {
            "message": {
                "token": token,
                "data": data,
                "webpush": {"headers": {"Urgency": "high", "TTL": "3600"}},
                "android": {
                    "priority": "HIGH",
                    "ttl": "3600s",
                    "notification": {
                        "title": data.get("title", ""),
                        "body": data.get("body", ""),
                        "channel_id": ANDROID_CHANNEL_ID,
                        "tag": data.get("tag", "reminder"),
                    },
                },
            }
        }
        try:
            response = await client.post(url, json=body, headers=headers)
        except httpx.HTTPError as exc:
            return SendOutcome(token, ok=False, error=str(exc) or type(exc).__name__)

        if response.is_success:
            return SendOutcome(token, ok=True)

        status, message, error_code = "", response.reason_phrase, ""
        try:
            error = response.json().get("error", {})
            status = error.get("status", "")
            message = error.get("message", message)
            for detail in error.get("details", []):
                error_code = detail.get("errorCode", error_code)
        except ValueError:
            pass

        # INVALID_ARGUMENT can also mean a bad payload, so only prune when the token is at fault.
        dead = error_code == "UNREGISTERED" or (
            status == "INVALID_ARGUMENT" and "registration token" in message.lower()
        )
        return SendOutcome(
            token,
            ok=False,
            dead=dead,
            error=f"{error_code or status or response.status_code}: {message}",
        )
