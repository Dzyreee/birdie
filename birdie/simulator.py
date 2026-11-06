"""Drives the simulated venues (always labelled "Simulated" in the UI).

Each step produces a raw observation per seat (PERSON / ITEMS / EMPTY) and feeds it to the venue's
VenueTracker.process: the same code path as camera frames, so smoothing, hold timers, SeatEvents and
booking check-ins all behave exactly like the live venue.

Seat dynamics are a simple birth-death process whose steady state is the forecast occupancy:
an occupied seat empties with probability dt / mean_stay; an empty seat fills with probability
dt / mean_stay * r / (1 - r), where r is the forecast ratio. Some leavers leave belongings behind
(ITEMS), which turns into HELD after the hold timer.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import datetime, timedelta

from birdie.booking import BookingService
from birdie.clock import Clock, FakeClock
from birdie.config import DEMO_MODE, PRODUCTION_TIMERS, Timers
from birdie.forecast.calendar import is_terrace_season
from birdie.models import BookingStatus, Seat, SeatState, VenueConfig, VenueSource
from birdie.storage import Repository
from birdie.vision.state import Observation, VenueTracker

OBS_TO_STATE = {Observation.EMPTY: SeatState.FREE, Observation.PERSON: SeatState.OCCUPIED, Observation.ITEMS: SeatState.OCCUPIED}


class Simulator:
    def __init__(
        self,
        configs: dict[str, VenueConfig],
        trackers: dict[str, VenueTracker],
        ratio_at: Callable[[str, datetime], float],
        clock: Clock,
        bookings: BookingService | None = None,
        seed: int = 7,
        fast: bool = DEMO_MODE,
    ) -> None:
        self.configs = configs
        self.trackers = trackers
        self.ratio_at = ratio_at
        self.clock = clock
        self.bookings = bookings
        self.rng = random.Random(seed)
        # Demo mode turns seats over faster so the simulated venues look alive during a 2-minute demo.
        self.mean_stay_s = 12 * 60 if fast else 75 * 60
        self.mean_away_s = 90 if fast else 12 * 60
        self.leave_items_p = 0.15
        self.obs: dict[str, dict[str, Observation]] = {}
        self._last_step: datetime | None = None

    def venue_ids(self) -> list[str]:
        return [vid for vid, c in self.configs.items() if c.venue.source == VenueSource.simulated]

    # --- dynamics ----------------------------------------------------------------
    def _seat_open(self, seat: Seat, now: datetime) -> bool:
        return seat.zone != "terrace" or is_terrace_season(now)

    def _initial_obs(self, venue_id: str, now: datetime) -> dict[str, Observation]:
        r = self.ratio_at(venue_id, now)
        obs = {}
        for seat in self.configs[venue_id].seats:
            u = self.rng.random()
            if not self._seat_open(seat, now) or u >= r:
                obs[seat.seat_id] = Observation.EMPTY
            elif u < r * 0.04:
                obs[seat.seat_id] = Observation.ITEMS
            else:
                obs[seat.seat_id] = Observation.PERSON
        return obs

    def _evolve(
        self,
        venue_id: str,
        obs: dict[str, Observation],
        now: datetime,
        dt: float,
        reserved: set[str] = frozenset(),
        seated: set[str] = frozenset(),
    ) -> None:
        r = min(0.97, max(0.0, self.ratio_at(venue_id, now)))
        p_leave = min(1.0, dt / self.mean_stay_s)
        if r < 0.02:  # closing time: everyone drifts out
            p_leave = min(1.0, dt / (5 * 60))
        p_arrive = min(1.0, dt / self.mean_stay_s * r / (1 - r))
        p_return = min(1.0, dt / self.mean_away_s)
        p_clear = min(1.0, dt / (self.mean_away_s * 4))
        for seat in self.configs[venue_id].seats:
            sid = seat.seat_id
            cur = obs.get(sid, Observation.EMPTY)
            if sid in seated:  # booked and QR scanned: the booker sits down
                obs[sid] = Observation.PERSON
                continue
            if sid in reserved:  # booked, not yet arrived: walk-ins leave it free
                obs[sid] = Observation.EMPTY if cur == Observation.EMPTY else cur
                if cur == Observation.EMPTY:
                    continue
            u = self.rng.random()
            if cur == Observation.PERSON:
                if u < p_leave:
                    obs[sid] = Observation.ITEMS if self.rng.random() < self.leave_items_p else Observation.EMPTY
            elif cur == Observation.ITEMS:
                if u < p_return and r >= 0.02:
                    obs[sid] = Observation.PERSON
                elif u < p_return + p_clear or r < 0.02:
                    obs[sid] = Observation.EMPTY
            else:
                if self._seat_open(seat, now) and u < p_arrive:
                    obs[sid] = Observation.PERSON

    def _booking_sets(self, venue_id: str) -> tuple[set[str], set[str]]:
        if self.bookings is None:
            return set(), set()
        reserved, seated = set(), set()
        for b in self.bookings.active_bookings(venue_id):
            if b.status == BookingStatus.BOOKED_PENDING:
                reserved.add(b.seat_id)
            else:  # QR_SCANNED or CHECKED_IN
                seated.add(b.seat_id)
        return reserved, seated

    # --- live ----------------------------------------------------------------------
    def start_venue(self, venue_id: str, obs: dict[str, Observation] | None = None) -> None:
        """Set the venue's initial seats without emitting events."""
        now = self.clock.now()
        obs = dict(obs) if obs is not None else self._initial_obs(venue_id, now)
        self.obs[venue_id] = obs
        self.trackers[venue_id].force({sid: OBS_TO_STATE[o] for sid, o in obs.items()})

    def step(self) -> None:
        """Advance every simulated venue by the time since the last step."""
        now = self.clock.now()
        dt = 2.0 if self._last_step is None else max(0.0, (now - self._last_step).total_seconds())
        self._last_step = now
        for vid in self.venue_ids():
            if vid not in self.obs:
                self.start_venue(vid)
            obs = self.obs[vid]
            for seat in self.configs[vid].seats:  # seats may have been added in the setup tool
                obs.setdefault(seat.seat_id, Observation.EMPTY)
            reserved, seated = self._booking_sets(vid)
            self._evolve(vid, obs, now, dt, reserved, seated)
            self.trackers[vid].process(obs)

    # --- synthetic event log ---------------------------------------------------------
    def backfill(
        self,
        repo: Repository,
        venue_id: str,
        hours: float = 24,
        step_minutes: float = 1,
        timers: Timers = PRODUCTION_TIMERS,
    ) -> dict[str, Observation]:
        """Simulate the last `hours` at production timings and store the events as synthetic.

        Returns the final observations so the live simulation continues from there.
        """
        end = self.clock.now()
        fake = FakeClock(end - timedelta(hours=hours))
        events = []
        cfg = self.configs[venue_id]
        tracker = VenueTracker(venue_id, cfg.seats, fake, on_event=events.append,
                               k=timers.smoothing_frames, hold_seconds=timers.hold_seconds)
        saved = (self.mean_stay_s, self.mean_away_s)
        self.mean_stay_s, self.mean_away_s = 75 * 60, 12 * 60  # realistic turnover for history
        try:
            obs = self._initial_obs(venue_id, fake.now())
            tracker.force({sid: OBS_TO_STATE[o] for sid, o in obs.items()})
            dt = step_minutes * 60
            while fake.now() < end:
                self._evolve(venue_id, obs, fake.now(), dt)
                tracker.process(obs)
                fake.advance(dt)
        finally:
            self.mean_stay_s, self.mean_away_s = saved
        repo.add_seat_events(events, synthetic=True)
        return obs
