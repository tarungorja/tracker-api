"""Background job that sends due dose reminders on a fixed interval."""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from app.schemas.push import ReminderRunResult

logger = logging.getLogger(__name__)


async def reminder_loop(
    run_once: Callable[[], Awaitable[ReminderRunResult]],
    interval_seconds: float,
    stop: asyncio.Event,
) -> None:
    """Runs `run_once` immediately, then every interval, until `stop` is set.

    A failing run is logged and never ends the loop. Overlapping runs (several workers, or this
    loop plus the /cron endpoint) are safe because each dose is only ever claimed once.
    """
    logger.info("Reminder timer started (every %ss)", interval_seconds)
    while not stop.is_set():
        try:
            result = await run_once()
            if result.notifications_sent or result.failures:
                logger.info("Reminder run: %s", result.model_dump(by_alias=True, exclude={"ok"}))
        except Exception:
            logger.exception("Reminder run failed")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
    logger.info("Reminder timer stopped")
