from app.schemas.common import CamelModel
from app.schemas.dose import DoseView
from app.utils.schedule import DoseStatus


class TimelineDose(DoseView):
    status: DoseStatus


class TimelineSlot(CamelModel):
    time: str
    minutes: int
    doses: list[TimelineDose]


class TodayData(CamelModel):
    today_key: str
    now_minutes: int
    slots: list[TimelineSlot]
    total: int
    completed: int
