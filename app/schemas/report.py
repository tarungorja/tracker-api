from typing import Literal

from app.schemas.common import CamelModel, OkResponse

ReportPeriod = Literal["last7"]
"""Reporting windows. Add "custom" (with a start and end date) here when it's needed."""


class ReportSendInput(CamelModel):
    period: ReportPeriod = "last7"


class ReportSendResult(OkResponse):
    email: str
    start_date: str
    end_date: str
