from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.dependencies import CurrentUser, ReportServiceDep
from app.schemas.report import ReportPeriod, ReportSendInput, ReportSendResult

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/send", response_model=ReportSendResult, summary="Email an adherence report")
async def send_report(
    body: ReportSendInput, user: CurrentUser, service: ReportServiceDep
) -> ReportSendResult:
    return await service.send(user.id, user.email, body.period)


@router.get(
    "/download",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
    summary="Download an adherence report as a PDF",
)
async def download_report(
    user: CurrentUser,
    service: ReportServiceDep,
    period: Annotated[ReportPeriod, Query()] = "last7",
) -> Response:
    filename, pdf = await service.render_download(user.id, user.email, period)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
