import math


def round_half_up(value: float, digits: int = 0) -> float:
    """Rounds halves upward, like JavaScript's Math.round.

    Python's built-in round() rounds halves to even (round(12.5) == 12), which would show
    different percentages than the original UI (13%).
    """
    factor = 10**digits
    return math.floor(value * factor + 0.5) / factor
