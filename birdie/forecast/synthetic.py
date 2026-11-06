"""Synthetic occupancy history (always labelled synthetic in the UI and the pitch).

Four weeks per venue in 15-minute buckets, shaped by venue type and the Qatar calendar:
Friday/Saturday weekend, quiet Friday mornings, Ramadan nights, exam season.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from birdie.clock import to_doha
from birdie.config import BUCKET_MINUTES, SYNTHETIC_HISTORY_WEEKS
from birdie.forecast import calendar as cal
from birdie.models import Venue, VenueType

# (hour, occupancy ratio) keypoints, linearly interpolated over the day.
_PROFILES: dict[tuple[str, str], list[tuple[float, float]]] = {
    # Libraries: afternoon study peak on weekdays; Friday closed/quiet until after prayer.
    ("library", "weekday"): [(0, 0.0), (7.5, 0.0), (8, 0.15), (10, 0.45), (12, 0.6), (13.5, 0.55), (15, 0.8),
                             (18, 0.85), (20, 0.65), (22, 0.35), (23, 0.1), (23.5, 0.0), (24, 0.0)],
    ("library", "friday"): [(0, 0.0), (13.5, 0.0), (14, 0.15), (16, 0.45), (19, 0.55), (21, 0.35), (22, 0.0), (24, 0.0)],
    ("library", "saturday"): [(0, 0.0), (8.5, 0.0), (9, 0.15), (11, 0.4), (14, 0.55), (17, 0.65), (20, 0.45),
                              (22, 0.15), (22.5, 0.0), (24, 0.0)],
    # Cafes: evening peak, busiest on weekend evenings, quiet Friday mornings.
    ("cafe", "weekday"): [(0, 0.35), (1, 0.15), (2, 0.0), (6.5, 0.0), (7, 0.2), (9, 0.4), (12, 0.3), (15, 0.35),
                          (17, 0.5), (20, 0.8), (22, 0.75), (23.5, 0.5), (24, 0.35)],
    ("cafe", "friday"): [(0, 0.45), (1.5, 0.2), (2, 0.0), (7, 0.0), (8, 0.08), (12.5, 0.1), (14, 0.45), (17, 0.6),
                         (20, 0.95), (23, 0.85), (24, 0.45)],
    ("cafe", "saturday"): [(0, 0.5), (1.5, 0.2), (2, 0.0), (7, 0.0), (8, 0.25), (11, 0.45), (14, 0.5), (17, 0.65),
                           (20, 0.9), (23, 0.8), (24, 0.5)],
    # Coworking: office hours on weekdays, light on the weekend.
    ("cowork", "weekday"): [(0, 0.0), (7, 0.0), (8, 0.2), (9.5, 0.65), (12, 0.75), (13, 0.6), (14, 0.8), (17, 0.6),
                            (19, 0.3), (21, 0.1), (22, 0.0), (24, 0.0)],
    ("cowork", "friday"): [(0, 0.0), (13, 0.0), (14, 0.1), (17, 0.2), (20, 0.1), (21, 0.0), (24, 0.0)],
    ("cowork", "saturday"): [(0, 0.0), (8, 0.0), (9, 0.15), (12, 0.35), (16, 0.3), (19, 0.15), (21, 0.0), (24, 0.0)],
}

# During Ramadan days are quiet (fasting) and the rush moves to the hours between iftar and suhoor.
_RAMADAN: dict[str, list[tuple[float, float]]] = {
    "cafe": [(0, 0.9), (2, 0.75), (3.5, 0.3), (4, 0.0), (9, 0.0), (10, 0.05), (17, 0.05), (18, 0.2), (19.5, 0.85),
             (21, 0.97), (24, 0.92)],
    "library": [(0, 0.35), (1, 0.0), (9, 0.0), (10, 0.25), (14, 0.4), (17, 0.25), (18, 0.05), (19.5, 0.0),
                (20, 0.5), (22, 0.7), (24, 0.35)],
    "cowork": [(0, 0.0), (9, 0.0), (10, 0.45), (14, 0.5), (15, 0.2), (16, 0.0), (20.5, 0.0), (21, 0.3), (23, 0.35),
               (24, 0.0)],
}

_EXAM_FACTOR = {"library": 1.3, "cafe": 1.1, "cowork": 1.0}


def _interp(points: list[tuple[float, float]], hour: float) -> float:
    xs, ys = zip(*points)
    return float(np.interp(hour, xs, ys))


def profile(
    venue_type: VenueType | str,
    ts: datetime,
    ramadan: bool | None = None,
    exam: bool | None = None,
) -> float:
    """Expected occupancy ratio (0..1) for a venue type at a time. Flags default to the calendar."""
    vt = venue_type.value if isinstance(venue_type, VenueType) else str(venue_type)
    ts = to_doha(ts)
    hour = ts.hour + ts.minute / 60
    ramadan = cal.is_ramadan(ts) if ramadan is None else ramadan
    exam = cal.is_exam_season(ts) if exam is None else exam
    if ramadan:
        value = _interp(_RAMADAN[vt], hour)
        if cal.is_weekend(ts) and vt != "cowork":
            value *= 1.05
    else:
        value = _interp(_PROFILES[(vt, cal.day_type(ts))], hour)
    if exam:
        value *= _EXAM_FACTOR[vt]
    return float(min(1.0, max(0.0, value)))


def generate_history(
    venue: Venue,
    n_seats: int,
    end: datetime,
    weeks: int = SYNTHETIC_HISTORY_WEEKS,
    seed: int | None = None,
    bucket_minutes: int = BUCKET_MINUTES,
) -> list[dict]:
    """Synthetic 15-minute buckets [{ts, venue_id, occupied, free, total, synthetic}] ending before `end`."""
    end = to_doha(end)
    end = end.replace(minute=end.minute - end.minute % bucket_minutes, second=0, microsecond=0)
    start = end - timedelta(weeks=weeks)
    if seed is None:
        seed = sum(ord(c) for c in venue.venue_id)
    rng = np.random.default_rng(seed)
    steps = int((end - start) / timedelta(minutes=bucket_minutes))
    out = []
    noise = 0.0
    day_factor = 1.0
    current_day = None
    for i in range(steps):
        ts = start + timedelta(minutes=i * bucket_minutes)
        if ts.date() != current_day:
            current_day = ts.date()
            day_factor = float(rng.normal(1.0, 0.08))
        noise = 0.8 * noise + float(rng.normal(0, 0.04))  # AR(1): busy spells last a while
        base = profile(venue.type, ts)
        ratio = 0.0 if base <= 0 else min(1.0, max(0.0, base * day_factor + noise))
        occupied = int(round(ratio * n_seats))
        out.append(
            {
                "ts": ts,
                "venue_id": venue.venue_id,
                "occupied": occupied,
                "free": n_seats - occupied,
                "total": n_seats,
                "synthetic": True,
            }
        )
    return out
