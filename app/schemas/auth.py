import re
from typing import Annotated

from pydantic import AfterValidator, StringConstraints, field_validator

from app.core.constants import OTP_LENGTH, OtpPurpose
from app.schemas.common import CamelModel, OkResponse

_EMAIL_RE = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")


def _check_email(value: str) -> str:
    if len(value) > 254 or not _EMAIL_RE.fullmatch(value):
        raise ValueError("Enter a valid email address.")
    return value


Email = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True),
    AfterValidator(_check_email),
]


class OtpRequestInput(CamelModel):
    email: Email
    purpose: OtpPurpose


class OtpVerifyInput(CamelModel):
    email: Email
    purpose: OtpPurpose
    code: str

    @field_validator("code")
    @classmethod
    def _check_code(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(rf"\d{{{OTP_LENGTH}}}", value, re.ASCII):
            raise ValueError(f"Enter the {OTP_LENGTH}-digit code.")
        return value


class UserView(CamelModel):
    id: str
    email: str


class VerifyOtpResponse(OkResponse):
    user: UserView
    # Also set as an HttpOnly cookie; returned for non-browser clients using Bearer auth.
    token: str
