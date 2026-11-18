from pydantic import Field

from app.schemas.common import CamelModel, OkResponse


class PushTokenInput(CamelModel):
    token: str = Field(min_length=20, max_length=4096)
    user_agent: str | None = Field(default=None, max_length=500)


class PushTokenRemoveInput(CamelModel):
    token: str = Field(min_length=1)


class TestNotificationResult(OkResponse):
    sent: int


class ReminderRunResult(OkResponse):
    users_checked: int
    doses_due: int
    notifications_sent: int
    failures: int
