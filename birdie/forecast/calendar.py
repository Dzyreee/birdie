"""Qatar calendar features (CLAUDE.md section 8.3).

- The weekend is Friday and Saturday.
- Friday mornings are quiet until after midday prayer.
- Ramadan and exam-season flags come from configurable date ranges (approximate; edit as needed).
"""

from __future__ import annotations

from datetime import date, datetime

from birdie.clock import to_doha

FRIDAY, SATURDAY = 4, 5  # datetime.weekday(): Monday = 0
WEEKEND_DAYS = frozenset({FRIDAY, SATURDAY})
FRIDAY_QUIET_UNTIL_HOUR = 13  # quiet until after Friday midday prayer

# Approximate dates; Ramadan follows the lunar calendar and moves ~11 days earlier each year.
RAMADAN_RANGES: list[tuple[date, date]] = [
    (date(2025, 3, 1), date(2025, 3, 30)),
    (date(2026, 2, 18), date(2026, 3, 19)),
    (date(2027, 2, 8), date(2027, 3, 9)),
]

# Approximate university final-exam periods (QU / Education City), when QNL fills up with students.
EXAM_RANGES: list[tuple[date, date]] = [
    (date(2025, 12, 7), date(2025, 12, 25)),
    (date(2026, 5, 10), date(2026, 5, 28)),
    (date(2026, 12, 6), date(2026, 12, 24)),
    (date(2027, 5, 9), date(2027, 5, 27)),
]


def _in_ranges(d: date, ranges: list[tuple[date, date]]) -> bool:
    return any(start <= d <= end for start, end in ranges)


def is_weekend(dt: datetime) -> bool:
    return to_doha(dt).weekday() in WEEKEND_DAYS


def day_type(dt: datetime) -> str:
    """'friday', 'saturday' or 'weekday' (Sunday to Thursday)."""
    wd = to_doha(dt).weekday()
    if wd == FRIDAY:
        return "friday"
    if wd == SATURDAY:
        return "saturday"
    return "weekday"


def is_friday_prayer_quiet(dt: datetime) -> bool:
    dt = to_doha(dt)
    return dt.weekday() == FRIDAY and dt.hour < FRIDAY_QUIET_UNTIL_HOUR


def is_ramadan(dt: datetime, ranges: list[tuple[date, date]] | None = None) -> bool:
    return _in_ranges(to_doha(dt).date(), RAMADAN_RANGES if ranges is None else ranges)


def is_exam_season(dt: datetime, ranges: list[tuple[date, date]] | None = None) -> bool:
    return _in_ranges(to_doha(dt).date(), EXAM_RANGES if ranges is None else ranges)


def is_terrace_season(dt: datetime) -> bool:
    """Outdoor terraces are used in the cooler months (roughly November to March)."""
    return to_doha(dt).month in (11, 12, 1, 2, 3)


def slot_of(dt: datetime, minutes: int = 15) -> int:
    dt = to_doha(dt)
    return (dt.hour * 60 + dt.minute) // minutes


def features(dt: datetime) -> dict:
    dt = to_doha(dt)
    return {
        "hour": dt.hour + dt.minute / 60,
        "slot": slot_of(dt),
        "day_type": day_type(dt),
        "weekend": is_weekend(dt),
        "friday_prayer_quiet": is_friday_prayer_quiet(dt),
        "ramadan": is_ramadan(dt),
        "exam_season": is_exam_season(dt),
        "terrace_season": is_terrace_season(dt),
    }
