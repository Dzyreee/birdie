"""BirdieService: the one object that holds all live state and that the UI talks to.

It wires the repository, the clock, one VenueTracker per venue, the camera pipeline,
the simulator, the forecaster and the decision logic. Framework-free.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from birdie.alerts import raise_held_alerts, resolve_on_event
from birdie.clock import Clock, RealClock
from birdie.config import (
    BLUR_THRESHOLD,
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
from birdie.vision.chairs import chair_candidates
from birdie.vision.detector import CHAIR, PERSON, resize_long_side
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
        # Camera state per venue, in memory only: when the last frame arrived, the last frame (for the seat
        # setup snapshot) and the person boxes in it (blurred again in the next frame, in case of a miss).
        self._last_frame_at: dict[str, datetime] = {}
        self._last_person_boxes: dict[str, list[list[float]]] = {}
        self._setup: dict[str, dict] = {}  # venue_id -> {"frame", "detections", "candidates"}

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
        """zone -> {total, FREE, OCCUPIED, HELD}."""
        zones = {s.seat_id: s.zone for s in self.seats(venue_id)}
        out: dict[str, dict[str, int]] = {}
        for z in self.venue(venue_id).zones:
            out[z] = {"total": 0, **{state.value: 0 for state in SeatState}}
        for snap in self.snapshots(venue_id):
            z = out.setdefault(zones.get(snap.seat_id, ""), {"total": 0, **{state.value: 0 for state in SeatState}})
            z["total"] += 1
            z[snap.state.value] += 1
        return out

    def set_seat_polygon(self, venue_id: str, seat_id: str, polygon: list[tuple[float, float]]) -> Seat:
        """Save a camera outline into an existing seat. Floor-plan fields are never touched."""
        with self._lock:
            cfg = self.configs[venue_id]
            if not any(s.seat_id == seat_id for s in cfg.seats):
                raise KeyError(f"{seat_id} is not a seat of {venue_id}")
            seats = [
                Seat.model_validate(s.model_dump() | {"polygon": [tuple(p) for p in polygon]})
                if s.seat_id == seat_id else s
                for s in cfg.seats
            ]
            self._replace_config(VenueConfig(venue=cfg.venue, seats=seats))
            return next(s for s in seats if s.seat_id == seat_id)

    def set_seat_polygons(self, venue_id: str, polygons: dict[str, list[tuple[float, float]]]) -> None:
        """Save several camera outlines at once (the "Detect chairs" mapping)."""
        with self._lock:
            cfg = self.configs[venue_id]
            unknown = set(polygons) - {s.seat_id for s in cfg.seats}
            if unknown:
                raise KeyError(f"not seats of {venue_id}: {sorted(unknown)}")
            seats = [
                Seat.model_validate(s.model_dump() | {"polygon": [tuple(p) for p in polygons[s.seat_id]]})
                if s.seat_id in polygons else s
                for s in cfg.seats
            ]
            self._replace_config(VenueConfig(venue=cfg.venue, seats=seats))

    def clear_seat_polygon(self, venue_id: str, seat_id: str) -> bool:
        """Remove a seat's camera outline (the seat stays on the floor plan)."""
        seat = self.seat(venue_id, seat_id)
        if seat is None or not seat.polygon:
            return False
        self.set_seat_polygon(venue_id, seat_id, [])
        return True

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
        """Run by the scheduler every ~2 s: simulator, timers, staff alerts and occupancy buckets.

        A live venue whose camera went offline keeps its last seat states: no timers, no buckets.
        """
        now = self.clock.now()
        self.simulator.step()
        for vid, tracker in self.trackers.items():
            if not self._frozen(vid):
                tracker.tick()  # OCCUPIED -> HELD even if no new frame arrives
        self._check_held_alerts(now)
        for vid in self.configs:
            if self._frozen(vid):
                continue
            c = self.counts(vid)
            self.repo.record_occupancy(vid, now, c[SeatState.FREE], c[SeatState.OCCUPIED], c[SeatState.HELD])
        if (now - self._last_refit).total_seconds() >= 15 * 60:
            self._last_refit = now
            self.forecast.refit()  # fold live buckets into the baseline

    def _check_held_alerts(self, now) -> None:
        for vid in self.configs:
            raise_held_alerts(self.repo, vid, self.snapshots(vid), now, self.timers.staff_alert_seconds)

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
        resolve_on_event(self.repo, event)
        for fn in self._listeners:
            try:
                fn(event)
            except Exception:  # a listener must never break the camera loop
                log.exception("seat event listener failed")

    # --- camera pipeline ------------------------------------------------------
    def camera_online(self, venue_id: str) -> bool | None:
        """True if the venue's camera sent a frame recently, False if not, None for simulated venues."""
        if self.venue(venue_id).source == VenueSource.simulated:
            return None
        last = self._last_frame_at.get(venue_id)
        return last is not None and (self.clock.now() - last).total_seconds() < self.timers.camera_stale_seconds

    def _frozen(self, venue_id: str) -> bool:
        """A camera venue that had frames but went quiet keeps its last states."""
        return venue_id in self._last_frame_at and self.camera_online(venue_id) is False

    def _detect_all(self, img) -> list[dict]:
        # One pass at the low blur threshold: people to blur, chairs, and the boxes that count.
        return self._detect(img, threshold=BLUR_THRESHOLD)

    def process_frame(self, venue_id: str | None, frame: np.ndarray, update_state: bool = True) -> np.ndarray:
        """One camera frame: detect, assign people and belongings to seat outlines (one per chair), update the
        seat states, and return the annotated frame (people blurred). The frame stays in memory.
        """
        img = resize_long_side(frame)
        arr = np.asarray(img)
        detections = self._detect_all(img)
        counted = [d for d in detections if d["score"] >= DETECTION_THRESHOLD and d["label"] != CHAIR]
        shown = counted + [d for d in detections if d["label"] == CHAIR and d["score"] >= DETECTION_THRESHOLD]
        persons = [d["box"] for d in detections if d["label"] == PERSON]
        key = venue_id or "_preview"
        blur = persons + self._last_person_boxes.get(key, [])
        self._last_person_boxes[key] = persons
        seats: list[Seat] = []
        snapshots: dict[str, SeatSnapshot] = {}
        if venue_id is not None:
            tracker = self.trackers[venue_id]
            seats = [s for s in tracker.seats.values() if len(s.polygon) >= 3]
            if update_state:
                self._last_frame_at[venue_id] = self.clock.now()
                assigned = assign_detections(counted, seats, img.size)
                tracker.process(observe(assigned))
            snapshots = self.snapshot_map(venue_id)
        return render.annotate(arr, shown, seats, snapshots, blur_boxes=blur)

    # --- seat setup (one seat per chair) ---------------------------------------------
    def set_setup_frame(self, venue_id: str, frame: np.ndarray) -> int:
        """Keep one snapshot for the seat setup tool (memory only) and run the detector on it.

        Returns the number of chairs found.
        """
        img = resize_long_side(frame)
        detections = self._detect_all(img)
        candidates = chair_candidates(detections, img.size)
        self._setup[venue_id] = {"frame": np.asarray(img), "detections": detections, "candidates": candidates}
        return len(candidates)

    def has_setup_frame(self, venue_id: str) -> bool:
        return venue_id in self._setup

    def chair_candidates(self, venue_id: str) -> list[dict]:
        return list(self._setup.get(venue_id, {}).get("candidates", []))

    def setup_view(self, venue_id: str, points: list[tuple[float, float]] | None = None,
                   show_candidates: bool = True) -> np.ndarray | None:
        """The snapshot with people blurred, saved seat outlines, numbered chair candidates and clicked corners."""
        setup = self._setup.get(venue_id)
        if setup is None:
            return None
        persons = [d["box"] for d in setup["detections"] if d["label"] == PERSON]
        img = render.blur_people(setup["frame"], persons)
        img = render.draw_seats(img, self.seats(venue_id), self.snapshot_map(venue_id))
        if show_candidates:
            img = render.draw_candidates(img, setup["candidates"])
        return render.draw_setup_points(img, points or [])
