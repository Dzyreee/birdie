"""Per-seat state machines with temporal smoothing and timestamp-based timers."""

from __future__ import annotations

import math
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from birdie.clock import Clock
from birdie.config import TIMERS
from birdie.models import Seat, SeatEvent, SeatSnapshot, SeatState


class Observation(str, Enum):
    UNKNOWN = "UNKNOWN"
    PERSON = "PERSON"
    ITEMS = "ITEMS"
    EMPTY = "EMPTY"


@dataclass(frozen=True)
class SeatEvidence:
    observation: Observation
    person_detected: bool | None = None
    belongings_detected: bool | None = None
    confidence: float | None = None


_STATE_TO_OBS = {
    SeatState.UNKNOWN: None,
    SeatState.FREE: Observation.EMPTY,
    SeatState.OCCUPIED: Observation.PERSON,
    SeatState.HELD: Observation.ITEMS,
    SeatState.REVIEW_REQUIRED: Observation.ITEMS,
    SeatState.UNAVAILABLE: None,
}


def _evidence(value: Observation | SeatEvidence) -> SeatEvidence:
    if isinstance(value, SeatEvidence):
        return value
    if value == Observation.UNKNOWN:
        return SeatEvidence(value, None, None, None)
    return SeatEvidence(
        value,
        person_detected=value == Observation.PERSON,
        belongings_detected=value == Observation.ITEMS,
    )


class SeatStateMachine:
    def __init__(
        self,
        venue_id: str,
        seat_id: str,
        clock: Clock,
        *,
        k: int | None = None,
        hold_seconds: float | None = None,
        initial: SeatState = SeatState.UNKNOWN,
        stale_seconds: float | None = TIMERS.camera_stale_seconds,
    ) -> None:
        self.venue_id = venue_id
        self.seat_id = seat_id
        self.clock = clock
        self.k = max(1, k if k is not None else TIMERS.smoothing_frames)
        self.hold = timedelta(seconds=hold_seconds if hold_seconds is not None else TIMERS.hold_seconds)
        self.stale = timedelta(seconds=stale_seconds) if stale_seconds is not None else None
        now = clock.now()
        self.state = initial
        self.since = now
        self.updated_at = now
        self._stable = _STATE_TO_OBS[initial]
        self._candidate: Observation | None = None
        self._count = 0
        self._candidate_since = now
        self.unattended_since = now if initial in (SeatState.HELD, SeatState.REVIEW_REQUIRED) else None
        self.person_detected: bool | None = initial == SeatState.OCCUPIED if initial != SeatState.UNKNOWN else None
        self.belongings_detected: bool | None = initial in (SeatState.HELD, SeatState.REVIEW_REQUIRED) if initial != SeatState.UNKNOWN else None
        self.confidence: float | None = None
        self.manual_override = initial == SeatState.UNAVAILABLE

    def update(self, observation: Observation | SeatEvidence) -> SeatEvent | None:
        """Feed one camera sample; UNKNOWN is immediate and can never increase availability."""
        evidence = _evidence(observation)
        now = self.clock.now()
        self.person_detected = evidence.person_detected
        self.belongings_detected = evidence.belongings_detected
        self.confidence = evidence.confidence
        if self.manual_override:
            self.updated_at = now
            return None
        obs = evidence.observation
        if obs == Observation.UNKNOWN:
            self._stable = None
            self._candidate = None
            self._count = 0
            self.unattended_since = None
            return self._apply(now)
        if obs == self._candidate:
            self._count += 1
        else:
            self._candidate = obs
            self._count = 1
            self._candidate_since = now
        if self._stable == Observation.EMPTY and obs in (Observation.PERSON, Observation.ITEMS):
            self._stable = None
        if self._stable == Observation.ITEMS and obs == Observation.PERSON:
            self._stable = None
            self.unattended_since = None
        if self._count >= self.k and obs != self._stable:
            self._stable = obs
            if obs == Observation.ITEMS:
                if self.unattended_since is None:
                    self.unattended_since = self._candidate_since
            else:
                self.unattended_since = None
        return self._apply(now)

    def tick(self) -> SeatEvent | None:
        """Advance real-time timers and expire stale camera evidence."""
        now = self.clock.now()
        if (
            self.stale is not None
            and self.state not in (SeatState.UNKNOWN, SeatState.UNAVAILABLE)
            and now - self.updated_at >= self.stale
        ):
            self._stable = None
            self._candidate = None
            self._count = 0
            self.person_detected = None
            self.belongings_detected = None
            self.confidence = None
            self.unattended_since = None
            return self._apply(now, touch=False)
        return self._apply(now, touch=False)

    def set_unavailable(self, unavailable: bool) -> SeatEvent | None:
        """Staff can disable a seat; re-enabling waits for fresh camera evidence."""
        now = self.clock.now()
        if unavailable == self.manual_override:
            return None
        self.manual_override = unavailable
        self._stable = None
        self._candidate = None
        self._count = 0
        self.person_detected = None
        self.belongings_detected = None
        self.confidence = None
        self.unattended_since = None
        new = SeatState.UNAVAILABLE if unavailable else SeatState.UNKNOWN
        return self._transition(new, now)

    def force(self, state: SeatState) -> SeatEvent | None:
        """Set a known state directly, used by simulation and staff tools."""
        now = self.clock.now()
        self.manual_override = state == SeatState.UNAVAILABLE
        self._stable = _STATE_TO_OBS[state]
        self._candidate = None
        self._count = 0
        self.unattended_since = now if state in (SeatState.HELD, SeatState.REVIEW_REQUIRED) else None
        self.person_detected = state == SeatState.OCCUPIED if state != SeatState.UNKNOWN else None
        self.belongings_detected = state in (SeatState.HELD, SeatState.REVIEW_REQUIRED) if state != SeatState.UNKNOWN else None
        self.confidence = None
        return self._transition(state, now)

    def restore(self, snapshot: SeatSnapshot) -> None:
        """Restore persisted state and timer timestamps after a process restart."""
        self.state = snapshot.state
        self.since = snapshot.state_changed_at or snapshot.since
        self.updated_at = snapshot.updated_at
        self.person_detected = snapshot.person_detected
        self.belongings_detected = snapshot.belongings_detected
        self.confidence = snapshot.confidence
        self.unattended_since = snapshot.unattended_since
        self.manual_override = snapshot.manual_override or snapshot.state == SeatState.UNAVAILABLE
        self._stable = _STATE_TO_OBS[snapshot.state]
        self._candidate = None
        self._count = 0
        self._candidate_since = snapshot.unattended_since or self.since

    def _apply(self, now: datetime, touch: bool = True) -> SeatEvent | None:
        if self.manual_override:
            new = SeatState.UNAVAILABLE
        elif self._stable is None:
            new = SeatState.UNKNOWN
        elif self._stable == Observation.PERSON:
            self.unattended_since = None
            new = SeatState.OCCUPIED
        elif self._stable == Observation.ITEMS:
            if self.unattended_since is None:
                self.unattended_since = self._candidate_since
            new = (
                SeatState.REVIEW_REQUIRED
                if now - self.unattended_since >= self.hold
                else SeatState.HELD
            )
        else:
            self.unattended_since = None
            new = SeatState.FREE
        if touch:
            self.updated_at = now
        if new == self.state:
            return None
        return self._transition(new, now)

    def _transition(self, new: SeatState, now: datetime) -> SeatEvent | None:
        if new == self.state:
            self.updated_at = now
            return None
        event = SeatEvent(ts=now, venue_id=self.venue_id, seat_id=self.seat_id,
                          old_state=self.state, new_state=new)
        self.state = new
        self.since = now
        self.updated_at = now
        return event

    def snapshot(self, seat: Seat) -> SeatSnapshot:
        now = self.clock.now()
        remaining = None
        if self.state == SeatState.HELD and self.unattended_since is not None:
            remaining = max(0, math.ceil((self.unattended_since + self.hold - now).total_seconds()))
        return SeatSnapshot(
            venue_id=self.venue_id,
            seat_id=self.seat_id,
            zone=seat.zone,
            has_outlet=seat.has_outlet,
            state=self.state,
            since=self.since,
            state_changed_at=self.since,
            updated_at=self.updated_at,
            person_detected=self.person_detected,
            belongings_detected=self.belongings_detected,
            confidence=self.confidence,
            unattended_since=self.unattended_since,
            grace_period_remaining_seconds=remaining,
            requires_staff_review=self.state == SeatState.REVIEW_REQUIRED,
            manual_override=self.manual_override,
        )


class VenueTracker:
    """All seat state machines of one venue; camera samples and simulation share this path."""

    def __init__(
        self,
        venue_id: str,
        seats: Iterable[Seat],
        clock: Clock,
        on_event: Callable[[SeatEvent], None] | None = None,
        *,
        k: int | None = None,
        hold_seconds: float | None = None,
        stale_seconds: float | None = TIMERS.camera_stale_seconds,
    ) -> None:
        self.venue_id = venue_id
        self.clock = clock
        self.on_event = on_event
        self._k = k
        self._hold = hold_seconds
        self.stale_seconds = stale_seconds
        self._lock = threading.RLock()
        self.seats: dict[str, Seat] = {}
        self.machines: dict[str, SeatStateMachine] = {}
        self.set_seats(seats)

    def _machine(self, seat_id: str, initial: SeatState = SeatState.UNKNOWN) -> SeatStateMachine:
        return SeatStateMachine(
            self.venue_id, seat_id, self.clock, k=self._k, hold_seconds=self._hold,
            initial=initial, stale_seconds=self.stale_seconds,
        )

    def set_seats(self, seats: Iterable[Seat]) -> None:
        with self._lock:
            new = {s.seat_id: s for s in seats}
            self.machines = {sid: self.machines.get(sid) or self._machine(sid) for sid in new}
            self.seats = new

    def restore(self, snapshots: Iterable[SeatSnapshot]) -> None:
        with self._lock:
            for snapshot in snapshots:
                machine = self.machines.get(snapshot.seat_id)
                if machine:
                    machine.restore(snapshot)

    def process(self, observations: dict[str, Observation | SeatEvidence]) -> list[SeatEvent]:
        events = []
        with self._lock:
            for seat_id, machine in self.machines.items():
                event = machine.update(observations.get(seat_id, Observation.UNKNOWN))
                if event:
                    events.append(event)
        self._emit(events)
        return events

    def tick(self) -> list[SeatEvent]:
        with self._lock:
            events = [e for e in (m.tick() for m in self.machines.values()) if e]
        self._emit(events)
        return events

    def set_unavailable(self, seat_id: str, unavailable: bool) -> SeatEvent | None:
        with self._lock:
            machine = self.machines.get(seat_id)
            event = machine.set_unavailable(unavailable) if machine else None
        if event:
            self._emit([event])
        return event

    def force(self, states: dict[str, SeatState], *, emit: bool = True) -> None:
        with self._lock:
            events = [e for sid, state in states.items() if (m := self.machines.get(sid)) and (e := m.force(state))]
        if emit:
            self._emit(events)

    def _emit(self, events: list[SeatEvent]) -> None:
        if self.on_event:
            for event in events:
                self.on_event(event)

    def snapshots(self) -> list[SeatSnapshot]:
        with self._lock:
            return [self.machines[sid].snapshot(seat) for sid, seat in self.seats.items()]

    def state_of(self, seat_id: str) -> SeatState | None:
        with self._lock:
            machine = self.machines.get(seat_id)
            return machine.state if machine else None

    def counts(self) -> dict[SeatState, int]:
        out = {state: 0 for state in SeatState}
        with self._lock:
            for machine in self.machines.values():
                out[machine.state] += 1
        return out
