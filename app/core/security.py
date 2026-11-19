"""Token and OTP hashing. Formats match the Next.js app so existing rows stay valid."""

import hashlib
import hmac
import secrets

from app.core.constants import INVITE_CODE_ALPHABET, INVITE_CODE_LENGTH, OTP_LENGTH


def generate_session_token() -> str:
    return secrets.token_hex(32)


def generate_refresh_token() -> str:
    return secrets.token_hex(32)


def hash_token(token: str) -> str:
    """sha256 of the opaque session token (only the hash is stored)."""
    return hashlib.sha256(token.encode()).hexdigest()


def generate_otp() -> str:
    return str(secrets.randbelow(10**OTP_LENGTH)).zfill(OTP_LENGTH)


def hash_otp(secret: str, email: str, code: str) -> str:
    return hmac.new(secret.encode(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


def verify_otp_hash(secret: str, email: str, code: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(secret, email, code), expected_hash)


def secrets_match(actual: str, expected: str) -> bool:
    return hmac.compare_digest(actual.encode(), expected.encode())


def generate_invite_code() -> str:
    """A short single-use code like "K7QM2XPD", from an alphabet without look-alike characters."""
    return "".join(secrets.choice(INVITE_CODE_ALPHABET) for _ in range(INVITE_CODE_LENGTH))


def normalize_invite_code(raw: str) -> str:
    """Accepts "k7qm-2xpd", "K7QM 2XPD", etc."""
    return "".join(ch for ch in raw.upper() if ch.isalnum())
