import base64
import json

import pytest

from app.integrations.fcm import FcmConfigError, parse_service_account

ACCOUNT = {
    "project_id": "p",
    "client_email": "svc@p.iam.gserviceaccount.com",
    "private_key": "-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----\\n",
}


def test_parses_raw_quoted_and_base64_json():
    raw = json.dumps(ACCOUNT)
    assert parse_service_account(raw)["project_id"] == "p"
    assert parse_service_account(f"'{raw}'")["project_id"] == "p"
    assert parse_service_account(json.dumps(raw))["project_id"] == "p"
    assert parse_service_account(base64.b64encode(raw.encode()).decode())["project_id"] == "p"


def test_tolerates_real_newlines_inside_private_key():
    raw = json.dumps(ACCOUNT).replace("\\\\n", "\n")
    assert parse_service_account(raw)["client_email"] == ACCOUNT["client_email"]


def test_rejects_garbage():
    with pytest.raises(FcmConfigError):
        parse_service_account("not json")


def _post_one(token: str = "tok") -> dict:
    """Runs FcmClient._send_one against a stub transport and returns the JSON body it posted."""
    import asyncio

    import httpx

    from app.integrations.fcm import FcmClient

    posted: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posted.append(json.loads(request.content))
        return httpx.Response(200, json={"name": "m"})

    async def go() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            outcome = await FcmClient._send_one(
                client,
                "https://fcm.test/send",
                {},
                token,
                {"title": "T", "body": "B", "url": "/today", "tag": "dose-1"},
            )
            assert outcome.ok

    asyncio.run(go())
    return posted[0]["message"]


def test_message_keeps_the_data_and_webpush_parts_for_browsers():
    message = _post_one()
    assert message["token"] == "tok"
    assert message["data"] == {"title": "T", "body": "B", "url": "/today", "tag": "dose-1"}
    assert message["webpush"] == {"headers": {"Urgency": "high", "TTL": "3600"}}


def test_message_carries_an_android_notification_for_the_native_app():
    android = _post_one()["android"]
    assert android["priority"] == "HIGH" and android["ttl"] == "3600s"
    assert android["notification"] == {
        "title": "T",
        "body": "B",
        "channel_id": "dose-reminders",
        "tag": "dose-1",
    }
