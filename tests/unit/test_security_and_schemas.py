import pytest
from pydantic import ValidationError

from app.core.security import (
    generate_otp,
    hash_otp,
    hash_token,
    secrets_match,
    verify_otp_hash,
)
from app.schemas.auth import OtpRequestInput, OtpVerifyInput
from app.schemas.medication import MedicationInput


def test_otp_is_six_digits():
    assert all(len(generate_otp()) == 6 and generate_otp().isdigit() for _ in range(50))


def test_otp_hash_roundtrip_and_known_format():
    digest = hash_otp("secret", "a@b.co", "123456")
    assert len(digest) == 64
    assert verify_otp_hash("secret", "a@b.co", "123456", digest)
    assert not verify_otp_hash("secret", "a@b.co", "654321", digest)
    assert not verify_otp_hash("other", "a@b.co", "123456", digest)


def test_token_hash_is_sha256_hex():
    # sha256("abc")
    assert hash_token("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_secrets_match():
    assert secrets_match("Bearer x", "Bearer x")
    assert not secrets_match("Bearer y", "Bearer x")


def test_email_is_trimmed_and_lowercased():
    body = OtpRequestInput(email="  Foo@Example.COM ", purpose="signin")
    assert body.email == "foo@example.com"
    with pytest.raises(ValidationError):
        OtpRequestInput(email="not-an-email", purpose="signin")
    with pytest.raises(ValidationError):
        OtpRequestInput(email="a@b.co", purpose="reset")


def test_otp_code_must_be_six_digits():
    assert OtpVerifyInput(email="a@b.co", purpose="signup", code=" 123456 ").code == "123456"
    with pytest.raises(ValidationError, match="6-digit"):
        OtpVerifyInput(email="a@b.co", purpose="signup", code="12345")


def test_medication_input_accepts_camel_case_payload():
    med = MedicationInput.model_validate(
        {"name": " Minoxidil ", "scheduleTimes": ["8:00 AM", "20:00"], "daysOfWeek": [1, 3]}
    )
    assert med.name == "Minoxidil"
    assert med.schedule_times == ["8:00 AM", "20:00"]
    assert med.description == ""


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"name": "  ", "scheduleTimes": ["8:00 AM"], "daysOfWeek": [1]}, "Name is required."),
        ({"name": "x", "scheduleTimes": [], "daysOfWeek": [1]}, "Add at least one time."),
        ({"name": "x", "scheduleTimes": ["soon"], "daysOfWeek": [1]}, "Enter a valid time."),
        (
            {"name": "x", "scheduleTimes": ["8:00 AM"], "daysOfWeek": []},
            "Pick at least one day of the week.",
        ),
        (
            {"name": "x", "scheduleTimes": ["8:00 AM"], "daysOfWeek": [7]},
            "Pick at least one day of the week.",
        ),
    ],
)
def test_medication_input_validation_messages(payload, message):
    with pytest.raises(ValidationError, match=message):
        MedicationInput.model_validate(payload)
