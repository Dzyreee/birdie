"""Decisions for drivers: availability at arrival, focus score, recommendations (CLAUDE.md 8.4, 8.5).

Functions take a `LiveData` object (the BirdieService implements it) so they can be tested with
any fake. Everything returns plain dataclasses with the numbers behind the answer, so the UI can
explain them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field  # noqa: F401  (field used by later dataclasses)
from datetime import datetime, timedelta
from typing import Protocol

from birdie.models import Booking, BookingStatus, Seat, SeatSnapshot, SeatState, Venue

LIVE_HALF_LIFE_MINUTES = 20.0  # live data counts half as much as the forecast at a 20-minute arrival


class LiveData(Protocol):
    def now(self) -> datetime: ...
    def venues(self) -> list[Venue]: ...
    def venue(self, venue_id: str) -> Venue: ...
    def seats(self, venue_id: str) -> list[Seat]: ...
    def snapshots(self, venue_id: str) -> list[SeatSnapshot]: ...
    def active_bookings(self, venue_id: str) -> list[Booking]: ...
    def forecast_ratio(self, venue_id: str, ts: datetime) -> float: ...


@dataclass
class Availability:
    venue_id: str
    arrival_minutes: int
    expected_free: float
    low: int
    high: int
    live_free: int
    forecast_free: float
    bookings_before: int
    total: int
    live_weight: float

    @property
    def expected_int(self) -> int:
        return int(round(self.expected_free))

    def summary(self) -> str:
        n = self.expected_int
        seats = "seat" if n == 1 else "seats"
        when = "now" if self.arrival_minutes <= 0 else f"when you arrive in {self.arrival_minutes} min"
        return f"about {n} {seats} likely free {when} (range {self.low} to {self.high})"


def blend_availability(
    *,
    venue_id: str,
    total: int,
    live_free: int,
    forecast_free_now: float,
    forecast_free_arrival: float,
    bookings_before: int,
    arrival_minutes: int,
) -> Availability:
    """Pure blending: live data dominates for short arrival times, the forecast for long ones.

    The live count is carried forward along the forecast trend (live_free + forecast change), then
    mixed with the plain forecast with weight w = 0.5 ** (arrival / 20 min). Bookings that start
    before arrival are subtracted. The range widens with the arrival time.
    """
    arrival_minutes = max(0, int(arrival_minutes))
    w = 0.5 ** (arrival_minutes / LIVE_HALF_LIFE_MINUTES)
    projected_live = live_free + (forecast_free_arrival - forecast_free_now)
    expected = w * projected_live + (1 - w) * forecast_free_arrival - bookings_before
    expected = float(min(total, max(0.0, expected)))
    spread = 0.5 + total * (0.03 + 0.12 * (1 - w))
    low = max(0, math.floor(expected - spread))
    high = min(total, math.ceil(expected + spread))
    return Availability(
        venue_id=venue_id,
        arrival_minutes=arrival_minutes,
        expected_free=round(expected, 2),
        low=low,
        high=high,
        live_free=live_free,
        forecast_free=round(forecast_free_arrival, 2),
        bookings_before=bookings_before,
        total=total,
        live_weight=round(w, 3),
    )


def _pending_bookings_before(data: LiveData, venue_id: str, arrival: datetime, free_ids: set[str]) -> list[Booking]:
    return [
        b
        for b in data.active_bookings(venue_id)
        if b.status in (BookingStatus.BOOKED_PENDING, BookingStatus.QR_SCANNED)
        and b.start_time <= arrival
        and b.seat_id in free_ids
    ]


def availability_at(data: LiveData, venue_id: str, arrival_minutes: int) -> Availability:
    """Expected free seats at `venue_id` when you arrive in `arrival_minutes`, with a low/high range."""
    now = data.now()
    arrival = now + timedelta(minutes=max(0, arrival_minutes))
    snaps = data.snapshots(venue_id)
    total = len(snaps)
    free_ids = {s.seat_id for s in snaps if s.state == SeatState.FREE}
    booked = _pending_bookings_before(data, venue_id, arrival, free_ids)
    return blend_availability(
        venue_id=venue_id,
        total=total,
        live_free=len(free_ids),
        forecast_free_now=total * (1 - data.forecast_ratio(venue_id, now)),
        forecast_free_arrival=total * (1 - data.forecast_ratio(venue_id, arrival)),
        bookings_before=len(booked),
        arrival_minutes=arrival_minutes,
    )

