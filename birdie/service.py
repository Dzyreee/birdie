"""BirdieService: the one object that holds all live state and that the UI talks to.

It wires the repository, the clock, one VenueTracker per venue, the camera pipeline,
the simulator, the forecaster and the decision logic. Framework-free.
"""

from __future__ import annotations

import logging
import hashlib
import threading
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import numpy as np
from shapely.geometry import Point, Polygon

from birdie.clock import Clock, RealClock
from birdie.config import (
    DETECTION_THRESHOLD,
    UNCERTAIN_DETECTION_THRESHOLD,
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
from birdie.vision.detector import PERSON, resize_long_side
from birdie.vision.seats import assign_detections, observe_evidence
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
        self.recorded_demo_status: dict = {"state": "not_configured"}
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
        for vid, cfg in self.configs.items():
            if cfg.venue.source != VenueSource.simulated:
                self.trackers[vid].restore(self.repo.seat_snapshots(vid))
                self.trackers[vid].tick()
                self.repo.save_seat_snapshots(self.trackers[vid].snapshots())
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

    def validate_recording(self, venue_id: str, path: str) -> None:
        """Reject a recording from another view when calibration is tied to a clip."""
        expected = self.configs[venue_id].recording_sha256
        if expected:
            with open(path, "rb") as video:
                actual = hashlib.file_digest(video, "sha256").hexdigest()
            if actual != expected:
                raise ValueError("This clip needs its own seat and mirror calibration")

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
            self._replace_config(cfg.model_copy(update={"venue": cfg.venue.model_copy(update={"zones": zones}), "seats": seats}))

    def delete_seat(self, venue_id: str, seat_id: str) -> bool:
        with self._lock:
            cfg = self.configs[venue_id]
            seats = [s for s in cfg.seats if s.seat_id != seat_id]
            if len(seats) == len(cfg.seats):
                return False
            self._replace_config(cfg.model_copy(update={"seats": seats}))
            return True

    def _replace_config(self, cfg: VenueConfig) -> None:
        self.configs[cfg.venue.venue_id] = cfg
        self.trackers[cfg.venue.venue_id].set_seats(cfg.seats)
        self.mark_unknown(cfg.venue.venue_id)
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
            tracker.tick()
            self.repo.save_seat_snapshots(tracker.snapshots())
        for vid in self.configs:
            c = self.counts(vid)
            # Partial samples would treat unknown seats as empty in historical occupancy ratios.
            if c[SeatState.UNKNOWN] == 0:
                self.repo.record_occupancy(
                    vid, now, c[SeatState.FREE],
                    c[SeatState.OCCUPIED] + c[SeatState.UNAVAILABLE],
                    c[SeatState.HELD] + c[SeatState.REVIEW_REQUIRED],
                )
        if (now - self._last_refit).total_seconds() >= 15 * 60:
            self._last_refit = now
            self.forecast.refit()  # fold live buckets into the baseline

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
        if event.new_state == SeatState.REVIEW_REQUIRED:
            self.repo.add_alert(
                event.ts, event.venue_id, event.seat_id, "review_required",
                f"Seat {event.seat_id} needs staff review: belongings remained after the grace period.",
            )
        elif event.new_state in (SeatState.FREE, SeatState.OCCUPIED, SeatState.UNAVAILABLE):
            self.repo.resolve_alerts(event.venue_id, event.seat_id, "review_required")
        for fn in self._listeners:
            try:
                fn(event)
            except Exception:  # a listener must never break the camera loop
                log.exception("seat event listener failed")

    # --- camera pipeline ------------------------------------------------------
    def process_frame(self, venue_id: str | None, frame: np.ndarray, update_state: bool = True) -> np.ndarray:
        """Detect objects, update calibrated seat states, and keep source frames in memory."""
        with self._lock:
            if venue_id is not None and venue_id not in self.trackers:
                raise KeyError(f"unknown venue: {venue_id}")
            config = self.configs.get(venue_id) if venue_id is not None else None
        try:
            arr = np.asarray(frame)
            if arr.ndim != 3 or arr.shape[0] <= 0 or arr.shape[1] <= 0 or arr.shape[2] not in (3, 4):
                raise ValueError("frame must be a non-empty RGB or RGBA image")
            img = resize_long_side(arr)
            detections = self._detect(img, threshold=UNCERTAIN_DETECTION_THRESHOLD)
            if config is not None:
                regions = [Polygon(points) for points in config.ignored_person_regions]
                w, h = img.size
                detections = [d for d in detections if d["label"] != PERSON or not any(
                    region.covers(Point((d["box"][0] + d["box"][2]) / (2 * w),
                                        (d["box"][1] + d["box"][3]) / (2 * h)))
                    for region in regions
                )]
        except Exception:
            if update_state and venue_id is not None:
                self.mark_unknown(venue_id)
            raise
        counted = [d for d in detections if d["score"] >= DETECTION_THRESHOLD]
        if update_state and venue_id is not None:
            with self._lock:
                if self.configs[venue_id] is not config:
                    self.mark_unknown(venue_id)
                else:
                    tracker = self.trackers[venue_id]
                    assigned = assign_detections(detections, list(tracker.seats.values()), img.size,
                                                 table_regions=config.camera_table_regions)
                    tracker.process(observe_evidence(assigned))
                    self.repo.save_seat_snapshots(tracker.snapshots())
        return render.annotate(np.asarray(img), counted)

    def mark_unknown(self, venue_id: str) -> None:
        """Invalidate all current venue evidence after a decode or camera failure."""
        tracker = self.trackers[venue_id]
        tracker.process({})
        self.repo.save_seat_snapshots(tracker.snapshots())

    def set_seat_unavailable(self, venue_id: str, seat_id: str, unavailable: bool) -> SeatSnapshot | None:
        tracker = self.trackers.get(venue_id)
        if tracker is None or seat_id not in tracker.seats:
            return None
        tracker.set_unavailable(seat_id, unavailable)
        snapshots = tracker.snapshots()
        self.repo.save_seat_snapshots(snapshots)
        return next(snapshot for snapshot in snapshots if snapshot.seat_id == seat_id)
