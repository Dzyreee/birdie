"""Staff alerts: a seat held by belongings with nobody there for too long (CLAUDE.md section 4).

One open alert per HELD episode; it is resolved when the seat goes FREE or OCCUPIED again.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from birdie.models import SeatEvent, SeatSnapshot, SeatState
from birdie.storage import Repository

HELD_TOO_LONG = "held_too_long"


def held_too_long(snapshots: list[SeatSnapshot], now: datetime, threshold_seconds: float) -> list[SeatSnapshot]:
    """Seats that have been HELD for at least the staff alert threshold."""
    limit = timedelta(seconds=threshold_seconds)
    return [s for s in snapshots if s.state == SeatState.HELD and now - s.since >= limit]


def raise_held_alerts(repo: Repository, venue_id: str, snapshots: list[SeatSnapshot], now: datetime,
                      threshold_seconds: float) -> list[str]:
    """Add an alert for every seat held too long that has no open alert yet. Returns the new seat ids."""
    snaps = held_too_long(snapshots, now, threshold_seconds)
    if not snaps:
        return []
    open_alerts = {a["seat_id"] for a in repo.alerts(venue_id, unresolved_only=True, limit=500)
                   if a["kind"] == HELD_TOO_LONG}
    new = []
    for snap in snaps:
        if snap.seat_id in open_alerts:
            continue
        minutes = (now - snap.since).total_seconds() / 60
        repo.add_alert(now, venue_id, snap.seat_id, HELD_TOO_LONG,
                       f"Seat {snap.seat_id} has been held by belongings with nobody there for {minutes:.1f} min.")
        new.append(snap.seat_id)
    return new


def resolve_on_event(repo: Repository, event: SeatEvent) -> None:
    """A seat that is FREE or OCCUPIED again no longer needs staff."""
    if event.new_state in (SeatState.FREE, SeatState.OCCUPIED):
        repo.resolve_alerts(event.venue_id, event.seat_id, HELD_TOO_LONG)
