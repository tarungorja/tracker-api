"""PushService.send_to_user: which tokens a push goes to."""

import asyncio

from app.integrations.fcm import SendOutcome
from app.services.push_service import PushPayload, PushService


class Sessions:
    async def active_ids_for_user(self, user_id):
        return ["s1"]


class Tokens:
    def __init__(self):
        self.asked: list[bool] = []

    async def delete_orphaned(self, user_id, session_ids):
        pass

    async def tokens_for_user(self, user_id, session_ids, include_native=True):
        self.asked.append(include_native)
        return ["web", "phone"] if include_native else ["web"]

    async def delete_by_tokens(self, tokens):
        pass


class Fcm:
    configured = True

    def __init__(self):
        self.sent_to: list[list[str]] = []

    async def send_many(self, tokens, data):
        self.sent_to.append(tokens)
        return [SendOutcome(t, ok=True) for t in tokens]


def send(include_native=None):
    tokens, fcm = Tokens(), Fcm()
    service = PushService(tokens, Sessions(), fcm)
    payload = PushPayload(title="t", body="b")
    kwargs = {} if include_native is None else {"include_native": include_native}
    result = asyncio.run(service.send_to_user("u1", payload, **kwargs))
    return result, tokens, fcm


def test_pushes_reach_the_android_app_by_default():
    result, tokens, fcm = send()
    assert tokens.asked == [True] and fcm.sent_to == [["web", "phone"]] and result.sent == 2


def test_native_tokens_can_be_left_out():
    result, tokens, fcm = send(include_native=False)
    assert tokens.asked == [False] and fcm.sent_to == [["web"]] and result.sent == 1
