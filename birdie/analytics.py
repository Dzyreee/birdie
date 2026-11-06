"""Venue dashboard numbers, all computed from the event log (seat events and booking events).

- occupancy by hour of day (time-weighted share of seats OCCUPIED or HELD)
- no-show rate (released bookings / bookings that either checked in or were released)
- minutes seats were HELD by belongings
- peak times
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from birdie.models import BookingStatus, SeatEvent, SeatState


@dataclass
class Dashboard:
    venue_id: str
    start: datetime
    end: datetime
    occupancy_by_hour: list[dict]  # [{hour, occupied_pct, held_pct}]
    peak_hours: list[dict]  # top hours by occupancy
    held_minutes_total: float
    held_minutes_by_seat: dict[str, float]
    no_show: dict  # {booked, showed, no_shows, rate}
    events_count: int
    includes_synthetic: bool = False
    notes: list[str] = field(default_factory=list)


def seat_intervals(
    events: list[SeatEvent], seat_ids: list[str], start: datetime, end: datetime
) -> dict[str, list[tuple[datetime, datetime, SeatState]]]:
    """Per seat, the (from, to, state) intervals covering [start, end], reconstructed from events.

    The state at `start` is the last state before it, or the first event's old state, or UNKNOWN.
    """
    by_seat: dict[str, list[SeatEvent]] = defaultdict(list)
    for e in sorted(events, key=lambda e: e.ts):
        by_seat[e.seat_id].append(e)
    out = {}
    for sid in seat_ids:
        evs = by_seat.get(sid, [])
        state = SeatState.UNKNOWN
        before = [e for e in evs if e.ts <= start]
        if before:
            state = before[-1].new_state
        elif evs and evs[0].old_state is not None:
            state = evs[0].old_state
        t = start
        intervals = []
        for e in evs:
            if e.ts <= start:
                continue
            if e.ts >= end:
                break
            intervals.append((t, e.ts, state))
            t, state = e.ts, e.new_state
        intervals.append((t, end, state))
        out[sid] = [iv for iv in intervals if iv[1] > iv[0]]
    return out


def _split_by_hour(a: datetime, b: datetime):
    """Yield (hour_of_day, seconds) pieces of [a, b)."""
    t = a
    while t < b:
        next_hour = t.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        piece_end = min(b, next_hour)
        yield t.hour, (piece_end - t).total_seconds()
        t = piece_end


def occupancy_by_hour(intervals: dict[str, list[tuple[datetime, datetime, SeatState]]]) -> list[dict]:
    total = defaultdict(float)
    occupied = defaultdict(float)
    held = defaultdict(float)
    for ivs in intervals.values():
        for a, b, state in ivs:
            if state == SeatState.UNKNOWN:
                continue
            for hour, secs in _split_by_hour(a, b):
                total[hour] += secs
                if state == SeatState.OCCUPIED:
                    occupied[hour] += secs
                elif state == SeatState.HELD:
                    held[hour] += secs
    rows = []
    for hour in range(24):
        if total[hour] <= 0:
            rows.append({"hour": hour, "occupied_pct": None, "held_pct": None})
            continue
        rows.append(
            {
                "hour": hour,
                "occupied_pct": round(100 * (occupied[hour] + held[hour]) / total[hour], 1),
                "held_pct": round(100 * held[hour] / total[hour], 1),
            }
        )
    return rows


def peak_hours(by_hour: list[dict], top: int = 3) -> list[dict]:
    rows = [r for r in by_hour if r["occupied_pct"]]
    return sorted(rows, key=lambda r: -r["occupied_pct"])[:top]


def held_minutes(intervals: dict[str, list[tuple[datetime, datetime, SeatState]]]) -> dict[str, float]:
    return {
        sid: round(sum((b - a).total_seconds() for a, b, s in ivs if s == SeatState.HELD) / 60, 1)
        for sid, ivs in intervals.items()
    }


def no_show_rate(booking_events: list[dict]) -> dict:
    """Of the bookings that resolved (checked in or released), the share released as no-shows."""
    reached: dict[str, set[str]] = defaultdict(set)
    for e in booking_events:
        reached[e["booking_id"]].add(e["new_status"])
    showed = sum(1 for s in reached.values() if BookingStatus.CHECKED_IN.value in s)
    no_shows = sum(
        1 for s in reached.values()
        if BookingStatus.NO_SHOW_RELEASED.value in s and BookingStatus.CHECKED_IN.value not in s
    )
    resolved = showed + no_shows
    return {
        "booked": len(reached),
        "showed": showed,
        "no_shows": no_shows,
        "rate": round(no_shows / resolved, 3) if resolved else None,
    }


def venue_dashboard(repo, venue_id: str, seat_ids: list[str], now: datetime, hours: float = 24,
                    include_synthetic: bool = True, observed_since: datetime | None = None) -> Dashboard:
    """Dashboard numbers for the last `hours`, but never before `observed_since` (when data starts)."""
    start = now - timedelta(hours=hours)
    if observed_since is not None:
        start = min(now, max(start, observed_since))
    events = repo.seat_events(venue_id, until=now, include_synthetic=include_synthetic)
    live_events = repo.seat_events(venue_id, since=start, until=now, include_synthetic=False)
    in_window = [e for e in events if e.ts >= start]
    intervals = seat_intervals(events, seat_ids, start, now)
    by_hour = occupancy_by_hour(intervals)
    held = held_minutes(intervals)
    has_synthetic = len(in_window) > len(live_events)
    notes = []
    if has_synthetic:
        notes.append("Includes a synthetic back-filled event log (simulated venue).")
    return Dashboard(
        venue_id=venue_id,
        start=start,
        end=now,
        occupancy_by_hour=by_hour,
        peak_hours=peak_hours(by_hour),
        held_minutes_total=round(sum(held.values()), 1),
        held_minutes_by_seat=held,
        no_show=no_show_rate(repo.booking_events(venue_id)),
        events_count=len(in_window),
        includes_synthetic=has_synthetic,
        notes=notes,
    )
