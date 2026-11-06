"""Seat state machine (CLAUDE.md section 8.1).

Per seat, per frame:
- a raw observation (PERSON, ITEMS or EMPTY) only counts after it holds for k consecutive frames;
- PERSON gives OCCUPIED;
- ITEMS keeps the seat OCCUPIED (the person stepped away) until items have been there with
  no person for the hold time, then HELD;
- EMPTY gives FREE.
Every state change becomes a SeatEvent. All timing goes through the injected clock.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from datetime import timedelta
from enum import Enum

from birdie.clock import Clock
from birdie.config import TIMERS
from birdie.models import Seat, SeatEvent, SeatSnapshot, SeatState


class Observation(str, Enum):
    PERSON = "PERSON"
    ITEMS = "ITEMS"
    EMPTY = "EMPTY"


_STATE_TO_OBS = {
    SeatState.FREE: Observation.EMPTY,
    SeatState.OCCUPIED: Observation.PERSON,
    SeatState.HELD: Observation.ITEMS,
}


class SeatStateMachine:
    def __init__(
        self,
        venue_id: str,
        seat_id: str,
        clock: Clock,
        *,
        k: int | None = None,
        hold_seconds: float | None = None,
        initial: SeatState = SeatState.FREE,
    ) -> None:
        self.venue_id = venue_id
        self.seat_id = seat_id
        self.clock = clock
        self.k = max(1, k if k is not None else TIMERS.smoothing_frames)
        self.hold = timedelta(seconds=hold_seconds if hold_seconds is not None else TIMERS.hold_seconds)
        now = clock.now()
        self.state = initial
        self.since = now
        self.updated_at = now
        self._stable = _STATE_TO_OBS[initial]
        self._candidate: Observation | None = None
        self._count = 0
        self._candidate_since = now
        # When belongings were first seen with no person (start of the hold timer).
        self._items_since = now - self.hold if initial == SeatState.HELD else None

    def update(self, obs: Observation) -> SeatEvent | None:
        """Feed one frame's raw observation. Returns a SeatEvent if the state changed."""
        now = self.clock.now()
        if obs == self._candidate:
            self._count += 1
        else:
            self._candidate = obs
            self._count = 1
            self._candidate_since = now
        if self._count >= self.k and obs != self._stable:
            self._stable = obs
            if obs == Observation.ITEMS:
                # The hold timer starts when the items were first seen alone, not after smoothing.
                self._items_since = self._candidate_since
        return self._apply(now)

    def tick(self) -> SeatEvent | None:
        """Apply time-based transitions (OCCUPIED -> HELD) without a new frame."""
        return self._apply(self.clock.now(), touch=False)

    def force(self, state: SeatState) -> None:
        """Set the state directly with no event (used to initialise simulated venues)."""
        now = self.clock.now()
        self.state = state
        self.since = now
        self.updated_at = now
        self._stable = _STATE_TO_OBS[state]
        self._candidate = None
        self._count = 0
        self._items_since = now - self.hold if state == SeatState.HELD else None

    def _apply(self, now, touch: bool = True) -> SeatEvent | None:
        if self._stable == Observation.PERSON:
            new = SeatState.OCCUPIED
            self._items_since = None
        elif self._stable == Observation.ITEMS:
            if self._items_since is None:
                self._items_since = now
            new = SeatState.HELD if now - self._items_since >= self.hold else SeatState.OCCUPIED
        else:
            new = SeatState.FREE
            self._items_since = None
        if touch:
            self.updated_at = now
        if new == self.state:
            return None
        event = SeatEvent(ts=now, venue_id=self.venue_id, seat_id=self.seat_id, old_state=self.state, new_state=new)
        self.state = new
        self.since = now
        self.updated_at = now
        return event

    def snapshot(self, seat: Seat) -> SeatSnapshot:
        return SeatSnapshot(
            venue_id=self.venue_id,
            seat_id=self.seat_id,
            zone=seat.zone,
            has_outlet=seat.has_outlet,
            state=self.state,
            since=self.since,
            updated_at=self.updated_at,
        )


class VenueTracker:
    """All seat state machines of one venue. Camera frames and the simulator both feed `process`."""

    def __init__(
        self,
        venue_id: str,
        seats: Iterable[Seat],
        clock: Clock,
        on_event: Callable[[SeatEvent], None] | None = None,
        *,
        k: int | None = None,
        hold_seconds: float | None = None,
    ) -> None:
        self.venue_id = venue_id
        self.clock = clock
        self.on_event = on_event
        self._k = k
        self._hold = hold_seconds
        self._lock = threading.RLock()
        self.seats: dict[str, Seat] = {}
        self.machines: dict[str, SeatStateMachine] = {}
        self.set_seats(seats)

    def _machine(self, seat_id: str, initial: SeatState = SeatState.FREE) -> SeatStateMachine:
        return SeatStateMachine(self.venue_id, seat_id, self.clock, k=self._k, hold_seconds=self._hold, initial=initial)

    def set_seats(self, seats: Iterable[Seat]) -> None:
        """Replace the seat layout, keeping state for seats that still exist."""
        with self._lock:
            new = {s.seat_id: s for s in seats}
            self.machines = {sid: self.machines.get(sid) or self._machine(sid) for sid in new}
            self.seats = new

    def process(self, observations: dict[str, Observation]) -> list[SeatEvent]:
        """One frame: an observation per seat (missing seats count as EMPTY)."""
        events = []
        with self._lock:
            for seat_id, machine in self.machines.items():
                event = machine.update(observations.get(seat_id, Observation.EMPTY))
                if event:
                    events.append(event)
        self._emit(events)
        return events

    def tick(self) -> list[SeatEvent]:
        with self._lock:
            events = [e for e in (m.tick() for m in self.machines.values()) if e]
        self._emit(events)
        return events

    def force(self, states: dict[str, SeatState]) -> None:
        with self._lock:
            for seat_id, state in states.items():
                if seat_id in self.machines:
                    self.machines[seat_id].force(state)

    def _emit(self, events: list[SeatEvent]) -> None:
        if self.on_event:
            for e in events:
                self.on_event(e)

    def snapshots(self) -> list[SeatSnapshot]:
        with self._lock:
            return [self.machines[sid].snapshot(seat) for sid, seat in self.seats.items()]

    def state_of(self, seat_id: str) -> SeatState | None:
        with self._lock:
            m = self.machines.get(seat_id)
            return m.state if m else None

    def counts(self) -> dict[SeatState, int]:
        out = {s: 0 for s in SeatState}
        with self._lock:
            for m in self.machines.values():
                out[m.state] += 1
        return out
