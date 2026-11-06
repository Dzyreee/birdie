"""BirdieService: the one object that holds all live state and that the UI talks to.

It wires the repository, the clock, one VenueTracker per venue, the camera pipeline,
the simulator, the forecaster and the decision logic. Framework-free.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import numpy as np

from birdie.clock import Clock, RealClock
from birdie.config import (
    DETECTION_THRESHOLD,
    SCHEDULER_INTERVAL_SECONDS,
    TIMERS,
    VENUES_DIR,
    Timers,
)
from birdie.decision import Availability, availability_at
from birdie.forecast.model import ForecastEngine
from birdie.models import Seat, SeatEvent, SeatSnapshot, SeatState, Venue, VenueConfig, VenueSource
from birdie.scheduler import Scheduler
from birdie.simulator import Simulator
from birdie.storage import Repository
from birdie.venues import load_all, save_venue
from birdie.vision import render
from birdie.vision.detector import resize_long_side
from birdie.vision.seats import assign_detections, observe
from birdie.vision.state import VenueTracker

log = logging.getLogger(__name__)

Detector = Callable[..., list[dict]]


def _default_detector(image, threshold: float = DETECTION_THRESHOLD) -> list[dict]:
    from birdie.vision.detector import detect

    return detect(image, threshold=threshold)


class BirdieService:
    def __init__(
        self,
        repo: Repository | None = None,
        clock: Clock | None = None,
        venues: dict[str, VenueConfig] | None = None,
        venues_dir: Path = VENUES_DIR,
        timers: Timers = TIMERS,
        detector: Detector | None = None,
        persist_venues: bool = True,
        forecast: ForecastEngine | None = None,
        seed: int = 7,
    ) -> None:
        self.clock = clock or RealClock()
        self.repo = repo or Repository()
        self.timers = timers
        self.venues_dir = Path(venues_dir)
        self.persist_venues = persist_venues
        self.configs: dict[str, VenueConfig] = venues if venues is not None else load_all(self.venues_dir)
        self._detect = detector or _default_detector
        self._lock = threading.RLock()
        self._listeners: list[Callable[[SeatEvent], None]] = []
        self.trackers: dict[str, VenueTracker] = {
            vid: VenueTracker(
                vid,
                cfg.seats,
                self.clock,
                on_event=self._on_seat_event,
                k=timers.smoothing_frames,
                hold_seconds=timers.hold_seconds,
                stale_seconds=(
                    timers.camera_stale_seconds if cfg.venue.source != VenueSource.simulated else None
                ),
            )
            for vid, cfg in self.configs.items()
        }
        self.forecast = forecast or ForecastEngine(self.configs, self.clock, self.repo)
        self.simulator = Simulator(
            self.configs, self.trackers, self.forecast.ratio_at, self.clock, seed=seed
        )
        self.scheduler = Scheduler(self.tick, SCHEDULER_INTERVAL_SECONDS)
        self._last_refit = self.clock.now()
        self.started_at = self.clock.now()
        self._observed_since: dict[str, object] = {vid: self.started_at for vid in self.configs}

    # --- venues and seats -------------------------------------------------------
    def venues(self) -> list[Venue]:
        return [c.venue for c in self.configs.values()]

    def venue(self, venue_id: str) -> Venue:
        return self.configs[venue_id].venue

    def seats(self, venue_id: str) -> list[Seat]:
        return list(self.configs[venue_id].seats)

    def seat(self, venue_id: str, seat_id: str) -> Seat | None:
        return next((s for s in self.configs[venue_id].seats if s.seat_id == seat_id), None)

    def camera_venues(self) -> list[Venue]:
        """Venues fed by a camera or a recorded clip (simulated venues are driven by the simulator)."""
        return [v for v in self.venues() if v.source != VenueSource.simulated]

    def snapshots(self, venue_id: str) -> list[SeatSnapshot]:
        return self.trackers[venue_id].snapshots()

    def snapshot_map(self, venue_id: str) -> dict[str, SeatSnapshot]:
        return {s.seat_id: s for s in self.snapshots(venue_id)}

    def state_of(self, venue_id: str, seat_id: str) -> SeatState | None:
        tracker = self.trackers.get(venue_id)
        return tracker.state_of(seat_id) if tracker else None

    def counts(self, venue_id: str) -> dict[SeatState, int]:
        return self.trackers[venue_id].counts()

    def zone_counts(self, venue_id: str) -> dict[str, dict[str, int]]:
        """zone -> {total, UNKNOWN, FREE, OCCUPIED, HELD}."""
        out: dict[str, dict[str, int]] = {}
        for z in self.venue(venue_id).zones:
            out[z] = {"total": 0, **{state.value: 0 for state in SeatState}}
        for snap in self.snapshots(venue_id):
            z = out.setdefault(snap.zone, {"total": 0, **{state.value: 0 for state in SeatState}})
            z["total"] += 1
            z[snap.state.value] += 1
        return out

    def upsert_seat(self, seat: Seat) -> None:
        """Add or replace a configured seat region and save the venue JSON."""
        with self._lock:
            cfg = self.configs[seat.venue_id]
            seats = [s for s in cfg.seats if s.seat_id != seat.seat_id] + [seat]
            seats.sort(key=lambda s: s.seat_id)
            zones = list(cfg.venue.zones)
            if seat.zone not in zones:
                zones.append(seat.zone)
            self._replace_config(VenueConfig(venue=cfg.venue.model_copy(update={"zones": zones}), seats=seats))

    def delete_seat(self, venue_id: str, seat_id: str) -> bool:
        with self._lock:
            cfg = self.configs[venue_id]
            seats = [s for s in cfg.seats if s.seat_id != seat_id]
            if len(seats) == len(cfg.seats):
                return False
            self._replace_config(VenueConfig(venue=cfg.venue, seats=seats))
            return True

    def _replace_config(self, cfg: VenueConfig) -> None:
        self.configs[cfg.venue.venue_id] = cfg
        self.trackers[cfg.venue.venue_id].set_seats(cfg.seats)
        if self.persist_venues:
            save_venue(cfg, self.venues_dir)

    # --- LiveData (used by birdie.decision) ----------------------------------------
    def now(self):
        return self.clock.now()

    def forecast_ratio(self, venue_id: str, ts) -> float:
        return self.forecast.ratio_at(venue_id, ts)

    def availability_at(self, venue_id: str, arrival_minutes: int) -> Availability:
        return availability_at(self, venue_id, arrival_minutes)

    # --- simulation -------------------------------------------------------------
    def setup_simulation(self, backfill_hours: float = 24) -> None:
        """Back-fill a synthetic event log for simulated venues, then continue live from its end state."""
        self.repo.delete_synthetic_events()
        now = self.clock.now()
        for vid in self.simulator.venue_ids():
            obs = self.simulator.backfill(self.repo, vid, hours=backfill_hours) if backfill_hours > 0 else None
            self.simulator.start_venue(vid, obs)
            self._observed_since[vid] = now - timedelta(hours=backfill_hours)

    def observed_since(self, venue_id: str):
        """When this process started having seat data for the venue (dashboard windows start here)."""
        return self._observed_since.get(venue_id, self.started_at)

    # --- background tick ------------------------------------------------------
    def tick(self) -> None:
        """Run by the scheduler every ~2 s: simulator, timers, staff alerts and occupancy buckets."""
        now = self.clock.now()
        self.simulator.step()
        for tracker in self.trackers.values():
            tracker.tick()  # OCCUPIED -> HELD even if no new frame arrives
        self._check_held_alerts(now)
        for vid in self.configs:
            c = self.counts(vid)
            # Partial samples would treat unknown seats as empty in historical occupancy ratios.
            if c[SeatState.UNKNOWN] == 0:
                self.repo.record_occupancy(vid, now, c[SeatState.FREE], c[SeatState.OCCUPIED], c[SeatState.HELD])
        if (now - self._last_refit).total_seconds() >= 15 * 60:
            self._last_refit = now
            self.forecast.refit()  # fold live buckets into the baseline

    def _check_held_alerts(self, now) -> None:
        threshold = self.timers.staff_alert_seconds
        for vid in self.configs:
            snaps = [
                snap for snap in self.snapshots(vid)
                if snap.state == SeatState.HELD and (now - snap.since).total_seconds() >= threshold
            ]
            if not snaps:
                continue
            open_alerts = {
                a["seat_id"] for a in self.repo.alerts(vid, unresolved_only=True, limit=500) if a["kind"] == "held_too_long"
            }
            for snap in snaps:
                if snap.seat_id not in open_alerts:
                    minutes = (now - snap.since).total_seconds() / 60
                    self.repo.add_alert(
                        now, vid, snap.seat_id, "held_too_long",
                        f"Seat {snap.seat_id} ({snap.zone}) has been held by belongings with nobody there "
                        f"for {minutes:.1f} min.",
                    )

    def start(self, backfill_hours: float = 24) -> None:
        """Seed the simulated venues and start the background scheduler."""
        self.setup_simulation(backfill_hours)
        self.scheduler.start()

    def stop(self) -> None:
        self.scheduler.stop()

    # --- events -----------------------------------------------------------------
    def add_listener(self, fn: Callable[[SeatEvent], None]) -> None:
        self._listeners.append(fn)

    def _on_seat_event(self, event: SeatEvent) -> None:
        self.repo.add_seat_event(event)
        if event.new_state in (SeatState.FREE, SeatState.OCCUPIED):
            self.repo.resolve_alerts(event.venue_id, event.seat_id, "held_too_long")
        for fn in self._listeners:
            try:
                fn(event)
            except Exception:  # a listener must never break the camera loop
                log.exception("seat event listener failed")

    # --- camera pipeline ------------------------------------------------------
    def process_frame(self, venue_id: str | None, frame: np.ndarray, update_state: bool = True) -> np.ndarray:
        """Detect objects and optionally update a calibrated venue's hidden seat states."""
        img = resize_long_side(frame)
        arr = np.asarray(img)
        detections = self._detect(img, threshold=DETECTION_THRESHOLD)
        counted = [d for d in detections if d["score"] >= DETECTION_THRESHOLD]
        if update_state and venue_id is not None:
            tracker = self.trackers[venue_id]
            seats = list(tracker.seats.values())
            assigned = assign_detections(counted, seats, img.size)
            tracker.process(observe(assigned))
        return render.annotate(arr, counted)
