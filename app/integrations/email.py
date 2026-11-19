"""Brevo transactional email over HTTPS (SMTP ports are often blocked)."""

import base64
import contextlib

import httpx

from app.core.config import Settings
from app.core.constants import OTP_TTL, OtpPurpose
from app.core.tls import httpx_verify

BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"


class EmailDeliveryError(Exception):
    """An email could not be sent (missing config or provider failure)."""


class BrevoEmailClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send_otp(self, to: str, code: str, purpose: OtpPurpose) -> None:
        app_name = self._settings.app_name
        minutes = round(OTP_TTL.total_seconds() / 60)
        action = "create your account" if purpose == "signup" else "sign in"

        text = "\n\n".join(
            [
                f"Your {app_name} verification code is {code}.",
                f"Use it to {action}. It expires in {minutes} minutes.",
                "If you didn't request this, you can ignore this email.",
            ]
        )
        html = (
            '<div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;'
            'max-width:420px;margin:0 auto;padding:24px;color:#18181b">'
            f'<h2 style="margin:0 0 8px;font-size:18px">{app_name}</h2>'
            f'<p style="margin:0 0 16px;color:#52525b">Use this code to {action}:</p>'
            '<p style="margin:0 0 16px;font-size:32px;font-weight:700;letter-spacing:8px">'
            f"{code}</p>"
            f'<p style="margin:0;color:#71717a;font-size:13px">This code expires in {minutes} '
            "minutes. If you didn't request it, you can safely ignore this email.</p></div>"
        )
        await self._send(to, f"{code} is your {app_name} verification code", html, text)

    async def send_report(
        self,
        to: str,
        subject: str,
        html: str,
        text: str,
        attachment: tuple[str, bytes] | None = None,
    ) -> None:
        """An adherence report, optionally with a file attached as (filename, bytes)."""
        await self._send(to, subject, html, text, attachment)

    async def _send(
        self,
        to: str,
        subject: str,
        html: str,
        text: str,
        attachment: tuple[str, bytes] | None = None,
    ) -> None:
        s = self._settings
        if not s.brevo_api_key:
            raise EmailDeliveryError("Missing BREVO_API_KEY. Add it to your environment variables.")
        if not s.email_from:
            raise EmailDeliveryError("Missing EMAIL_FROM. Add it to your environment variables.")

        payload: dict[str, object] = {
            "sender": {"name": s.email_sender_name, "email": s.email_from},
            "to": [{"email": to}],
            "subject": subject,
            "htmlContent": html,
            "textContent": text,
        }
        if attachment:
            name, content = attachment
            payload["attachment"] = [{"name": name, "content": base64.b64encode(content).decode()}]
        headers = {
            "api-key": s.brevo_api_key,
            "content-type": "application/json",
            "accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                timeout=15, verify=httpx_verify(s.use_system_ca)
            ) as client:
                response = await client.post(BREVO_ENDPOINT, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise EmailDeliveryError(f"Email provider error: {exc or type(exc).__name__}") from exc

        if response.is_success:
            return
        detail = f"{response.status_code} {response.reason_phrase}"
        with contextlib.suppress(ValueError, AttributeError):
            detail = response.json().get("message") or detail
        raise EmailDeliveryError(f"Email provider error: {detail}")
