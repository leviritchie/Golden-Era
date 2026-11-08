"""Calendar and recurrence encoders for QuestScript timed grants.

Decomp (ConStartTurn / ConCounterEqualityInDays / ConAnyStartTurn):

- ``StartTurn`` parameters are **week, day-of-week** (not side, day). Side
  audience comes from quest ``sharing: Clone`` / ``forSides``. Absolute campaign
  days encode as continuous week numbers (day 30 → week 5 day 2), not month-local
  wrap at 28.
- ``AnyStartTurn`` parameters are **month, week, day** (all optional / -1).
- ``CounterEqualityInDays`` means: on each ``SideStartTurn``, fire when the
  named counter's **value equals** p[1]. It is **not** an N-day interval opcode.

Interval recurrence therefore needs a daily ``CounterPlus`` tick plus CED on the
interval value, with the timer starting far below the interval so CED cannot
fire before the first ``StartTurn`` grant resets the timer to 0.
"""

from __future__ import annotations

from typing import Any

# Far below any campaign interval so daily CounterPlus cannot hit CED early.
TIMER_PREARM_VALUE = -1_000_000


def absolute_day_to_week_day(absolute_day: int, *, context: str) -> tuple[int, int]:
    """Map 1-based absolute day onto ``StartTurn`` week + day-of-week.

    ``StartTurn`` has no month parameter. Encode continuous campaign days as
    unbounded week numbers (day 1 → week 1 day 1, day 30 → week 5 day 2) so
    briefings and timed grants after day 28 do not wrap back into month 1.
    Validators reconstruct absolute day as ``(week - 1) * 7 + day_of_week``.
    """

    day = int(absolute_day)
    if day < 1:
        raise ValueError(f"{context}: absolute day must be >= 1; got {day}")
    idx = day - 1
    week = idx // 7 + 1
    day_of_week = idx % 7 + 1
    return week, day_of_week


def start_turn_condition(absolute_day: int, *, context: str) -> dict[str, Any]:
    week, day_of_week = absolute_day_to_week_day(absolute_day, context=context)
    return {
        "comment": "",
        "c": "StartTurn",
        "p": [str(week), str(day_of_week)],
        "counter": 1,
    }


def any_start_turn_every_day_condition() -> dict[str, Any]:
    """Match every side start turn (month/week/day unrestricted)."""

    return {"comment": "", "c": "AnyStartTurn", "p": [], "counter": 1}


def counter_equality_in_days_condition(counter_sid: str, value: int) -> dict[str, Any]:
    return {
        "comment": "",
        "c": "CounterEqualityInDays",
        "p": [str(counter_sid), str(int(value))],
        "counter": 1,
    }


def counter_set_action(counter_sid: str, value: int | str) -> dict[str, Any]:
    return {"comment": "", "a": "CounterSet", "p": [str(counter_sid), str(value)]}


def counter_plus_action(counter_sid: str, value: int | str = 1) -> dict[str, Any]:
    return {"comment": "", "a": "CounterPlus", "p": [str(counter_sid), str(value)]}


def timer_counter_row(counter_sid: str, *, sharing: str = "Clone") -> dict[str, Any]:
    return {
        "comment": "",
        "sid": counter_sid,
        "sharing": sharing,
        "value": TIMER_PREARM_VALUE,
        "minValue": -2147483648,
        "maxValue": 2147483647,
    }
