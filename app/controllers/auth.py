from fastapi import APIRouter, Request, Response

from app.core.config import Settings
from app.core.constants import REFRESH_COOKIE_PATH
from app.core.exceptions import UnauthorizedError
from app.dependencies import (
    AccountServiceDep,
    AuthServiceDep,
    CurrentUser,
    SettingsDep,
    extract_session_token,
)
from app.schemas.auth import (
    OtpRequestInput,
    OtpVerifyInput,
    RefreshInput,
    UserView,
    VerifyOtpResponse,
)
from app.schemas.common import OkResponse
from app.services.auth_service import IssuedSession
from app.utils.time import to_iso_z

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookies(response: Response, issued: IssuedSession, settings: Settings) -> None:
    """Both cookies live as long as the session. The access token inside `session` stops being
    accepted sooner; that is how the web app knows to refresh, while its middleware can still see
    the cookie. The refresh cookie is only ever sent to the auth endpoints."""
    response.set_cookie(
        key=settings.session_cookie_name,
        value=issued.token,
        httponly=True,
        samesite=settings.cookie_samesite,
        secure=settings.secure_cookies,
        path="/",
        expires=issued.expires_at,
    )
    if issued.refresh_token:
        response.set_cookie(
            key=settings.refresh_cookie_name,
            value=issued.refresh_token,
            httponly=True,
            samesite=settings.cookie_samesite,
            secure=settings.secure_cookies,
            path=REFRESH_COOKIE_PATH,
            expires=issued.expires_at,
        )


def _clear_session_cookies(response: Response, settings: Settings) -> None:
    for name, path in (
        (settings.session_cookie_name, "/"),
        (settings.refresh_cookie_name, REFRESH_COOKIE_PATH),
    ):
        response.delete_cookie(
            name,
            path=path,
            httponly=True,
            samesite=settings.cookie_samesite,
            secure=settings.secure_cookies,
        )


def _session_response(issued: IssuedSession) -> VerifyOtpResponse:
    return VerifyOtpResponse(
        user=issued.user,
        token=issued.token,
        refresh_token=issued.refresh_token,
        access_expires_at=to_iso_z(issued.access_expires_at) if issued.access_expires_at else None,
    )


@router.post("/otp/request", response_model=OkResponse, summary="Email a sign-in/sign-up code")
async def request_otp(body: OtpRequestInput, service: AuthServiceDep) -> OkResponse:
    await service.request_otp(body.email, body.purpose)
    return OkResponse()


@router.post(
    "/otp/verify",
    response_model=VerifyOtpResponse,
    summary="Verify the code, create the account if signing up, and start a session",
)
async def verify_otp(
    body: OtpVerifyInput,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
) -> VerifyOtpResponse:
    issued = await service.verify_otp(body.email, body.purpose, body.code, body.use_refresh_token)
    _set_session_cookies(response, issued, settings)
    return _session_response(issued)


@router.post(
    "/refresh",
    response_model=VerifyOtpResponse,
    summary="Trade a refresh token for a new access + refresh token (the old ones stop working)",
)
async def refresh(
    request: Request,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
    body: RefreshInput | None = None,
) -> VerifyOtpResponse:
    token = request.cookies.get(settings.refresh_cookie_name) or (body and body.refresh_token)
    if not token:
        raise UnauthorizedError("Not signed in.")
    issued = await service.refresh(token)
    _set_session_cookies(response, issued, settings)
    return _session_response(issued)


@router.get("/me", response_model=UserView, summary="The signed-in user")
async def me(user: CurrentUser) -> UserView:
    return UserView(id=user.id, email=user.email)


@router.delete(
    "/me",
    response_model=OkResponse,
    summary="Permanently delete the account and all of its data",
)
async def delete_account(
    response: Response,
    user: CurrentUser,
    service: AccountServiceDep,
    settings: SettingsDep,
) -> OkResponse:
    await service.delete_account(user.id, user.email)
    _clear_session_cookies(response, settings)
    return OkResponse()


@router.post("/signout", response_model=OkResponse, summary="End this device's session")
async def sign_out(
    request: Request,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
) -> OkResponse:
    await service.sign_out(
        extract_session_token(request, settings), request.cookies.get(settings.refresh_cookie_name)
    )
    _clear_session_cookies(response, settings)
    return OkResponse()
