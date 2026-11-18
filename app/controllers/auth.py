from fastapi import APIRouter, Request, Response

from app.dependencies import (
    AccountServiceDep,
    AuthServiceDep,
    CurrentUser,
    SettingsDep,
    extract_session_token,
)
from app.schemas.auth import OtpRequestInput, OtpVerifyInput, UserView, VerifyOtpResponse
from app.schemas.common import OkResponse

router = APIRouter(prefix="/auth", tags=["auth"])


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
    issued = await service.verify_otp(body.email, body.purpose, body.code)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=issued.token,
        httponly=True,
        samesite=settings.cookie_samesite,
        secure=settings.secure_cookies,
        path="/",
        expires=issued.expires_at,
    )
    return VerifyOtpResponse(user=issued.user, token=issued.token)


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
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        httponly=True,
        samesite=settings.cookie_samesite,
        secure=settings.secure_cookies,
    )
    return OkResponse()


@router.post("/signout", response_model=OkResponse, summary="End this device's session")
async def sign_out(
    request: Request,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
) -> OkResponse:
    token = extract_session_token(request, settings)
    if token:
        await service.sign_out(token)
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        httponly=True,
        samesite=settings.cookie_samesite,
        secure=settings.secure_cookies,
    )
    return OkResponse()
