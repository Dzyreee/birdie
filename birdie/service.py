"""BirdieService: the one object that holds all live state and that the UI talks to.

It wires the repository, the clock, one VenueTracker per venue, the camera pipeline,
bookings, the simulator, the forecaster and the decision logic. Framework-free.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np

from birdie.booking import BookingService, held_too_long
from birdie.clock import Clock, RealClock
from birdie.config import (
    BLUR_THRESHOLD,
    DETECTION_THRESHOLD,
    SCHEDULER_INTERVAL_SECONDS,
    TIMERS,
    VENUES_DIR,
    Timers,
)
from birdie.models import Booking, Seat, SeatEvent, SeatSnapshot, SeatState, Venue, VenueConfig, VenueSource
from birdie.scheduler import Scheduler
from birdie.storage import Repository
from birdie.venues import load_all, save_venue
from birdie.vision import render
from birdie.vision.detector import PERSON, resize_long_side
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
        # Last camera frame per venue, kept in memory only for the seat setup snapshot.
        self._last_frame: dict[str, np.ndarray] = {}
        self._last_person_boxes: dict[str, list[list[float]]] = {}
        self.bookings = BookingService(self.repo, self.clock, self.configs, self.state_of, timers)
        self.add_listener(self.bookings.on_seat_event)
        self.scheduler = Scheduler(self.tick, SCHEDULER_INTERVAL_SECONDS)

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
        out: dict[str, dict[str, int]] = {}
        for z in self.venue(venue_id).zones:
            out[z] = {"total": 0, "FREE": 0, "OCCUPIED": 0, "HELD": 0}
        for snap in self.snapshots(venue_id):
            z = out.setdefault(snap.zone, {"total": 0, "FREE": 0, "OCCUPIED": 0, "HELD": 0})
            z["total"] += 1
            z[snap.state.value] += 1
        return out

    def upsert_seat(self, seat: Seat) -> None:
        """Add or replace a seat (seat setup tool) and save the venue JSON."""
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

    def active_booking_by_seat(self, venue_id: str) -> dict[str, Booking]:
        return {b.seat_id: b for b in self.bookings.active_bookings(venue_id)}

    # --- background tick ------------------------------------------------------
    def tick(self) -> None:
        """Run by the scheduler every ~2 s: timers, bookings, staff alerts, occupancy buckets."""
        now = self.clock.now()
        for tracker in self.trackers.values():
            tracker.tick()  # OCCUPIED -> HELD even if no new frame arrives
        self.bookings.tick()
        self._check_held_alerts(now)
        for vid in self.configs:
            c = self.counts(vid)
            self.repo.record_occupancy(vid, now, c[SeatState.FREE], c[SeatState.OCCUPIED], c[SeatState.HELD])

    def _check_held_alerts(self, now) -> None:
        threshold = self.timers.staff_alert_seconds
        for vid in self.configs:
            snaps = held_too_long(self.snapshots(vid), now, threshold)
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

    def start(self) -> None:
        """Start the background scheduler."""
        self.scheduler.start()

    def stop(self) -> None:
        self.scheduler.stop()

    # --- events -----------------------------------------------------------------
    def add_listener(self, fn: Callable[[SeatEvent], None]) -> None:
        self._listeners.append(fn)

    def _on_seat_event(self, event: SeatEvent) -> None:
        self.repo.add_seat_event(event)
        if event.old_state == SeatState.HELD:
            self.repo.resolve_alerts(event.venue_id, event.seat_id, "held_too_long")
        for fn in self._listeners:
            try:
                fn(event)
            except Exception:  # a listener must never break the camera loop
                log.exception("seat event listener failed")

    # --- camera pipeline ------------------------------------------------------
    def process_frame(self, venue_id: str, frame: np.ndarray, update_state: bool = True) -> np.ndarray:
        """One camera frame: detect, assign to seats, update seat states, return the annotated frame.

        The frame stays in memory. Only the most recent one is kept (for the seat setup snapshot).
        """
        img = resize_long_side(frame)
        arr = np.asarray(img)
        detections = self._detect(img, threshold=BLUR_THRESHOLD)
        counted = [d for d in detections if d["score"] >= DETECTION_THRESHOLD]
        tracker = self.trackers[venue_id]
        seats = list(tracker.seats.values())
        if update_state:
            assigned = assign_detections(counted, seats, img.size)
            tracker.process(observe(assigned))
        persons = [d["box"] for d in detections if d["label"] == PERSON]
        # Also blur where people were in the previous frame, in case the detector missed them this time.
        blur = persons + self._last_person_boxes.get(venue_id, [])
        self._last_person_boxes[venue_id] = persons
        self._last_frame[venue_id] = arr
        return render.annotate(arr, seats, self.snapshot_map(venue_id), counted, blur_boxes=blur)

    def setup_frame(self, venue_id: str, points: list[tuple[float, float]] | None = None) -> np.ndarray | None:
        """The last camera frame with people blurred, current seats and the setup corners drawn."""
        arr = self._last_frame.get(venue_id)
        if arr is None:
            return None
        blurred = render.blur_people(arr, self._last_person_boxes.get(venue_id, []))
        img = render.annotate(blurred, self.seats(venue_id), self.snapshot_map(venue_id), [], show_boxes=False)
        return render.draw_setup_points(img, points or [])

    def has_frame(self, venue_id: str) -> bool:
        return venue_id in self._last_frame
