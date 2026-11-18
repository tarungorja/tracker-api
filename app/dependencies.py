"""Dependency wiring: DB -> repositories -> services, plus authentication."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header, Request
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings, get_settings
from app.core.exceptions import UnauthorizedError
from app.core.security import secrets_match
from app.db import mongo
from app.db.repositories import (
    DailyLogRepository,
    MedicationRepository,
    OtpRepository,
    PushTokenRepository,
    ReminderSentRepository,
    SessionRepository,
    UserRepository,
)
from app.integrations.email import BrevoEmailClient
from app.integrations.fcm import FcmClient
from app.services.account_service import AccountService
from app.services.auth_service import AuthService, AuthUser
from app.services.dashboard_service import DashboardService
from app.services.dose_service import DoseService
from app.services.medication_service import MedicationService
from app.services.push_service import PushService
from app.services.reminder_service import ReminderService
from app.services.schedule_service import ScheduleService
from app.services.statistics_service import StatisticsService
from app.services.today_service import TodayService
from app.services.wellness_service import WellnessService

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_db() -> AsyncDatabase:
    return mongo.get_database()


DbDep = Annotated[AsyncDatabase, Depends(get_db)]


@lru_cache
def _fcm_client() -> FcmClient:
    settings = get_settings()
    return FcmClient(settings.firebase_service_account, settings.use_system_ca)


# ---- services ------------------------------------------------------------------------------


def get_auth_service(db: DbDep, settings: SettingsDep) -> AuthService:
    return AuthService(
        UserRepository(db),
        OtpRepository(db),
        SessionRepository(db),
        PushTokenRepository(db),
        BrevoEmailClient(settings),
        settings,
    )


def get_account_service(db: DbDep) -> AccountService:
    return AccountService(
        UserRepository(db),
        SessionRepository(db),
        OtpRepository(db),
        PushTokenRepository(db),
        MedicationRepository(db),
        DailyLogRepository(db),
        ReminderSentRepository(db),
    )


def get_schedule_service(db: DbDep) -> ScheduleService:
    return ScheduleService(MedicationRepository(db), DailyLogRepository(db))


ScheduleServiceDep = Annotated[ScheduleService, Depends(get_schedule_service)]


def get_medication_service(db: DbDep, schedule: ScheduleServiceDep) -> MedicationService:
    return MedicationService(MedicationRepository(db), DailyLogRepository(db), schedule)


def get_dose_service(db: DbDep) -> DoseService:
    return DoseService(DailyLogRepository(db))


def get_dashboard_service(schedule: ScheduleServiceDep) -> DashboardService:
    return DashboardService(schedule)


def get_today_service(schedule: ScheduleServiceDep) -> TodayService:
    return TodayService(schedule)


def get_statistics_service(db: DbDep, schedule: ScheduleServiceDep) -> StatisticsService:
    return StatisticsService(DailyLogRepository(db), schedule)


def get_wellness_service(db: DbDep) -> WellnessService:
    return WellnessService(DailyLogRepository(db))


def get_push_service(db: DbDep) -> PushService:
    return PushService(PushTokenRepository(db), SessionRepository(db), _fcm_client())


PushServiceDep = Annotated[PushService, Depends(get_push_service)]


def get_reminder_service(db: DbDep, push: PushServiceDep) -> ReminderService:
    return ReminderService(
        PushTokenRepository(db),
        MedicationRepository(db),
        DailyLogRepository(db),
        ReminderSentRepository(db),
        push,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]
MedicationServiceDep = Annotated[MedicationService, Depends(get_medication_service)]
DoseServiceDep = Annotated[DoseService, Depends(get_dose_service)]
DashboardServiceDep = Annotated[DashboardService, Depends(get_dashboard_service)]
TodayServiceDep = Annotated[TodayService, Depends(get_today_service)]
StatisticsServiceDep = Annotated[StatisticsService, Depends(get_statistics_service)]
WellnessServiceDep = Annotated[WellnessService, Depends(get_wellness_service)]
ReminderServiceDep = Annotated[ReminderService, Depends(get_reminder_service)]


# ---- authentication ------------------------------------------------------------------------


def extract_session_token(request: Request, settings: Settings) -> str | None:
    """Session token from the HttpOnly cookie, or an `Authorization: Bearer` header."""
    cookie = request.cookies.get(settings.session_cookie_name)
    if cookie:
        return cookie
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


async def get_current_user(
    request: Request, settings: SettingsDep, auth: AuthServiceDep
) -> AuthUser:
    token = extract_session_token(request, settings)
    user = await auth.authenticate(token) if token else None
    if user is None:
        raise UnauthorizedError("Not signed in.")
    return user


CurrentUser = Annotated[AuthUser, Depends(get_current_user)]


def require_cron_secret(
    settings: SettingsDep, authorization: Annotated[str, Header()] = ""
) -> None:
    """Scheduler calls must send `Authorization: Bearer $CRON_SECRET`."""
    secret = settings.cron_secret
    if not secret or not secrets_match(authorization, f"Bearer {secret}"):
        raise UnauthorizedError("Unauthorized")
