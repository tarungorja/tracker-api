import asyncio

from app.schemas.push import ReminderRunResult
from app.tasks.reminder_loop import reminder_loop

RESULT = ReminderRunResult(users_checked=1, doses_due=1, notifications_sent=1, failures=0)


async def _run_loop(run_once, runs_wanted: int) -> None:
    stop = asyncio.Event()
    calls = 0

    async def counting() -> ReminderRunResult:
        nonlocal calls
        calls += 1
        if calls >= runs_wanted:
            stop.set()
        return await run_once()

    await asyncio.wait_for(reminder_loop(counting, 0.01, stop), timeout=2)


def test_runs_repeatedly_until_stopped():
    seen = []

    async def run_once():
        seen.append(1)
        return RESULT

    asyncio.run(_run_loop(run_once, 3))
    assert len(seen) == 3


def test_a_failing_run_does_not_end_the_loop():
    seen = []

    async def run_once():
        seen.append(1)
        if len(seen) == 1:
            raise RuntimeError("boom")
        return RESULT

    asyncio.run(_run_loop(run_once, 3))
    assert len(seen) == 3
