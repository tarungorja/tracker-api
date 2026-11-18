from fastapi import APIRouter, Depends

from app.dependencies import ReminderServiceDep, require_cron_secret
from app.schemas.push import ReminderRunResult

router = APIRouter(prefix="/cron", tags=["cron"], dependencies=[Depends(require_cron_secret)])


async def _send_reminders_get(service: ReminderServiceDep) -> ReminderRunResult:
    return await service.send_due()


async def _send_reminders_post(service: ReminderServiceDep) -> ReminderRunResult:
    return await service.send_due()


# Call every minute from an external scheduler with `Authorization: Bearer $CRON_SECRET`.
# Both verbs are accepted because schedulers differ (the original Next.js route did the same).
for _endpoint, _method in ((_send_reminders_get, "GET"), (_send_reminders_post, "POST")):
    router.add_api_route(
        "/send-reminders",
        _endpoint,
        methods=[_method],
        response_model=ReminderRunResult,
        summary="Send due dose reminders (scheduler only)",
    )
