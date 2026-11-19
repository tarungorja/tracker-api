import os
from datetime import timedelta
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ENV_FILE lets a deployment or the test-suite pick another file (or none) than ./.env.
    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Medication Tracker"
    environment: Literal["development", "production", "test"] = "development"
    api_prefix: str = "/api/v1"

    mongodb_uri: str
    mongodb_db: str | None = None
    ensure_indexes_on_startup: bool = True

    auth_secret: str

    session_cookie_name: str = "session"
    session_ttl_days: int = 30
    # Clients that opt in to refresh tokens get an access token that is only valid this long.
    access_token_ttl_minutes: int = 15
    refresh_cookie_name: str = "refresh_token"
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_secure: bool | None = None

    cors_origins: str = "http://localhost:3000"

    brevo_api_key: str | None = None
    email_from: str | None = None
    email_from_name: str | None = None

    firebase_service_account: str | None = None
    cron_secret: str | None = None
    use_system_ca: bool = False

    # In-process reminder job (replaces the Next.js instrumentation timer). Overlapping runs
    # are safe: every dose is claimed once. Turn off when an external scheduler calls
    # /cron/send-reminders instead (e.g. serverless hosting).
    reminder_timer_enabled: bool = True
    reminder_interval_seconds: int = 60

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.environment == "production" or self.cookie_samesite == "none"

    @property
    def session_ttl(self) -> timedelta:
        """How long a session (and its refresh token) lasts without being used."""
        return timedelta(days=self.session_ttl_days)

    @property
    def access_token_ttl(self) -> timedelta:
        return timedelta(minutes=self.access_token_ttl_minutes)

    @property
    def email_sender_name(self) -> str:
        return self.email_from_name or self.app_name


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
