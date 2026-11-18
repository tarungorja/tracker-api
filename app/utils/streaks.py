from collections.abc import Callable, Iterable

from app.utils.time import add_days_to_key

_MAX_STREAK_DAYS = 4000


def longest_streak(ordered_keys: Iterable[str], is_success: Callable[[str], bool]) -> int:
    best = 0
    run = 0
    for key in ordered_keys:
        if is_success(key):
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def current_streak(
    today_key: str,
    is_success: Callable[[str], bool],
    grace_today: bool = True,
) -> int:
    """Consecutive successful days ending today (or yesterday when today is still open)."""
    cursor = today_key
    streak = 0

    if grace_today and not is_success(cursor):
        cursor = add_days_to_key(cursor, -1)

    for _ in range(_MAX_STREAK_DAYS):
        if not is_success(cursor):
            break
        streak += 1
        cursor = add_days_to_key(cursor, -1)
    return streak
