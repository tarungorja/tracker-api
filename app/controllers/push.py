from fastapi import APIRouter

from app.dependencies import CurrentUser, PushServiceDep
from app.schemas.common import OkResponse
from app.schemas.push import PushTokenInput, PushTokenRemoveInput, TestNotificationResult

router = APIRouter(prefix="/push", tags=["push"])


@router.post("/tokens", response_model=OkResponse, summary="Register this browser's FCM token")
async def save_push_token(
    body: PushTokenInput, user: CurrentUser, service: PushServiceDep
) -> OkResponse:
    await service.save_token(user.id, user.session_id, body)
    return OkResponse()


@router.delete("/tokens", response_model=OkResponse, summary="Unregister an FCM token")
async def remove_push_token(
    body: PushTokenRemoveInput, user: CurrentUser, service: PushServiceDep
) -> OkResponse:
    await service.remove_token(user.id, body.token)
    return OkResponse()


@router.post("/test", response_model=TestNotificationResult, summary="Send a test notification")
async def send_test_notification(
    user: CurrentUser, service: PushServiceDep
) -> TestNotificationResult:
    return TestNotificationResult(sent=await service.send_test(user.id))
