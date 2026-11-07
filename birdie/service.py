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
from birdie.models import (
    Seat, SeatEvent, SeatSnapshot, SeatState, StudyTable, TableType, Venue, VenueConfig, VenueSource,
)
from birdie.scheduler import Scheduler
from birdie.simulator import Simulator
from birdie.storage import Repository
from birdie.venues import load_all, save_venue
from birdie.vision import render
from birdie.vision.detector import BELONGINGS, PERSON, resize_long_side
from birdie.vision.motion import FrameAligner, warp_polygon
from birdie.vision.seats import assign_detections, observe_evidence, workspace_evidence
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
        self._workspace_evidence: dict[str, dict[str, dict]] = {vid: {} for vid in self.configs}
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
        self._aligners: dict[str, FrameAligner] = {}  # hand-held clips only (VenueConfig.stabilize_camera)

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

    def study_availability(self, venue_id: str) -> dict:
        """Compute verified study spaces from the saved venue layout and latest camera evidence."""
        config = self.configs[venue_id]
        snapshots = self.snapshot_map(venue_id)
        evidence = self._workspace_evidence.get(venue_id, {})
        seats = {seat.seat_id: seat for seat in config.seats}
        tables = {table.table_id: table for table in config.tables}
        by_seat = {}
        for seat_id, seat in seats.items():
            table = tables.get(seat.table_id)
            proof = evidence.get(seat_id, {})
            workspace_clear = proof.get("clear")
            confidence = proof.get("confidence")
            chair_detected = proof.get("chair_detected", False)
            state = snapshots[seat_id].state
            if table is None or seat_id not in table.seat_ids:
                reason = "seat_not_linked_to_table"
            elif not table.is_available_for_studying:
                reason = "table_unavailable"
            elif len(seat.seat_polygon) < 3 or len(seat.workspace_polygon) < 3 or len(table.table_polygon) < 3:
                reason = "camera_calibration_incomplete"
            elif state != SeatState.FREE:
                reason = {
                    SeatState.OCCUPIED: "seat_occupied",
                    SeatState.HELD: "workspace_blocked_by_belongings",
                    SeatState.REVIEW_REQUIRED: "workspace_blocked_staff_review",
                    SeatState.UNAVAILABLE: "seat_unavailable",
                }.get(state, "seat_state_unknown")
            elif workspace_clear is False:
                reason = "workspace_blocked"
            elif workspace_clear is None:
                reason = "workspace_uncertain" if chair_detected else "chair_not_visible"
            elif confidence is None or confidence < DETECTION_THRESHOLD:
                reason = "detection_confidence_too_low"
            else:
                reason = "available"
            by_seat[seat_id] = {
                "table_id": seat.table_id,
                "seat_id": seat_id,
                "seat_state": state.value,
                "workspace_clear": workspace_clear,
                "confidence": confidence,
                "usable_for_studying": reason == "available",
                "availability_reason": reason,
            }

        table_rows = []
        usable_spaces = usable_seats = 0
        for table in config.tables:
            rows = [by_seat[sid] for sid in table.seat_ids if sid in by_seat]
            complete = len(rows) == table.capacity and len(table.table_polygon) >= 3
            exclusive = table.table_type == TableType.private or not table.is_shareable
            if exclusive:
                ready = complete and table.is_available_for_studying and all(
                    row["usable_for_studying"] for row in rows
                )
                if not ready:
                    for row in rows:
                        if row["usable_for_studying"]:
                            row["usable_for_studying"] = False
                            row["availability_reason"] = "private_table_in_use_or_unverified"
                count = int(ready)
            else:
                count = sum(row["usable_for_studying"] for row in rows)
            usable_spaces += count
            usable_seats += sum(row["usable_for_studying"] for row in rows)
            table_rows.append({
                "table_id": table.table_id,
                "table_type": table.table_type.value,
                "capacity": table.capacity,
                "seat_ids": table.seat_ids,
                "is_shareable": table.is_shareable,
                "is_available_for_studying": table.is_available_for_studying,
                "layout_complete": complete,
                "usable_for_studying": count > 0,
                "usable_study_spaces": count,
                "seats": rows,
                "availability_reason": "available" if count else (
                    "table_layout_incomplete" if not complete else "no_verified_usable_workspace"
                ),
            })
        return {"usable_study_spaces": usable_spaces, "usable_seats": usable_seats,
                "tables": table_rows, "seats": list(by_seat.values())}

    def set_table_available_for_studying(self, venue_id: str, table_id: str, available: bool) -> StudyTable | None:
        """Persist a staff table-level override and require fresh camera evidence afterward."""
        with self._lock:
            config = self.configs.get(venue_id)
            if config is None:
                return None
            tables = [
                table.model_copy(update={"is_available_for_studying": available})
                if table.table_id == table_id else table
                for table in config.tables
            ]
            updated = next((table for table in tables if table.table_id == table_id), None)
            if updated is None:
                return None
            self.configs[venue_id] = config.model_copy(update={"tables": tables})
            if self.persist_venues:
                save_venue(self.configs[venue_id], self.venues_dir)
        self.mark_unknown(venue_id)
        return updated

    def upsert_seat(self, seat: Seat) -> None:
        """Add or replace a configured seat region and save the venue JSON."""
        with self._lock:
            cfg = self.configs[seat.venue_id]
            if cfg.tables and (not seat.table_id or not seat.workspace_polygon):
                raise ValueError("Seats in a table layout need a table_id and workspace_polygon before saving")
            seats = [s for s in cfg.seats if s.seat_id != seat.seat_id] + [seat]
            seats.sort(key=lambda s: s.seat_id)
            zones = list(cfg.venue.zones)
            if seat.zone not in zones:
                zones.append(seat.zone)
            tables = cfg.tables
            if cfg.tables:
                if seat.table_id not in {table.table_id for table in cfg.tables}:
                    raise ValueError(f"Unknown table {seat.table_id}; add it to the venue layout first")
                tables = [
                    table.model_copy(update={"seat_ids": list(dict.fromkeys([*table.seat_ids, seat.seat_id]))})
                    if table.table_id == seat.table_id else table
                    for table in cfg.tables
                ]
            pending = [seat_id for seat_id in cfg.unmapped_seat_ids if seat_id != seat.seat_id]
            updated = cfg.model_copy(update={
                "venue": cfg.venue.model_copy(update={"zones": zones}), "seats": seats,
                "tables": tables, "unmapped_seat_ids": pending,
            })
            self._replace_config(VenueConfig.model_validate(updated.model_dump(mode="python")))

    def delete_seat(self, venue_id: str, seat_id: str) -> bool:
        with self._lock:
            cfg = self.configs[venue_id]
            seats = [s for s in cfg.seats if s.seat_id != seat_id]
            if len(seats) == len(cfg.seats):
                return False
            tables = []
            for table in cfg.tables:
                ids = [sid for sid in table.seat_ids if sid != seat_id]
                if ids:
                    tables.append(table.model_copy(update={"seat_ids": ids}))
            updated = cfg.model_copy(update={"seats": seats, "tables": tables})
            self._replace_config(VenueConfig.model_validate(updated.model_dump(mode="python")))
            return True

    def _replace_config(self, cfg: VenueConfig) -> None:
        cfg = VenueConfig.model_validate(cfg.model_dump(mode="python"))
        self.configs[cfg.venue.venue_id] = cfg
        self.trackers[cfg.venue.venue_id].set_seats(cfg.seats)
        self._workspace_evidence[cfg.venue.venue_id] = {}
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
            before = {snap.seat_id: snap.state for snap in tracker.snapshots()}
            tracker.tick()
            snapshots = tracker.snapshots()
            for snap in snapshots:
                if before.get(snap.seat_id) != SeatState.UNKNOWN and snap.state == SeatState.UNKNOWN:
                    self._workspace_evidence.get(snap.venue_id, {}).pop(snap.seat_id, None)
            self.repo.save_seat_snapshots(snapshots)
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
            floor = UNCERTAIN_DETECTION_THRESHOLD
            if config is not None and config.belongings_threshold:
                floor = min(floor, config.belongings_threshold)
            detections = self._detect(img, threshold=floor)
            if config is not None and config.belongings_threshold:
                # This clip's belongings are scored low by the pretrained model: count them as confident.
                detections = [
                    {**d, "score": max(d["score"], DETECTION_THRESHOLD)}
                    if d["label"] in BELONGINGS and d["score"] >= config.belongings_threshold else d
                    for d in detections
                ]
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
                self._workspace_evidence[venue_id] = {}
                self.mark_unknown(venue_id)
            raise
        counted = [d for d in detections if d["score"] >= DETECTION_THRESHOLD]
        if update_state and venue_id is not None:
            with self._lock:
                if self.configs[venue_id] is not config:
                    self.mark_unknown(venue_id)
                else:
                    tracker = self.trackers[venue_id]
                    tables = {table.table_id: table.table_polygon for table in config.tables}
                    tables.update({key: value for key, value in config.camera_table_regions.items() if key not in tables})
                    seats_now = list(tracker.seats.values())
                    if config.stabilize_camera and any(seat.seat_polygon for seat in seats_now):
                        h = self._aligners.setdefault(venue_id, FrameAligner()).update(np.asarray(img))
                        seats_now = [
                            seat.model_copy(update={"seat_polygon": warp_polygon(seat.seat_polygon, h),
                                                    "workspace_polygon": warp_polygon(seat.workspace_polygon, h)})
                            for seat in seats_now
                        ]
                        tables = {key: warp_polygon(value, h) for key, value in tables.items()}
                    assigned = assign_detections(detections, seats_now, img.size, table_regions=tables)
                    tracker.process(observe_evidence(assigned))
                    proof = workspace_evidence(detections, seats_now, img.size, table_regions=tables)
                    self._workspace_evidence[venue_id] = {
                        seat_id: {"clear": item.clear, "confidence": item.confidence,
                                  "chair_detected": item.chair_detected}
                        for seat_id, item in proof.items()
                    }
                    self.repo.save_seat_snapshots(tracker.snapshots())
        return render.annotate(np.asarray(img), counted)

    def reset_alignment(self, venue_id: str) -> None:
        """Start of a clip pass: the next frame becomes the reference the seat outlines were drawn on."""
        self._aligners.setdefault(venue_id, FrameAligner()).reset()

    def mark_unknown(self, venue_id: str) -> None:
        """Invalidate all current venue evidence after a decode or camera failure."""
        self._workspace_evidence[venue_id] = {}
        tracker = self.trackers[venue_id]
        tracker.process({})
        self.repo.save_seat_snapshots(tracker.snapshots())

    def set_seat_unavailable(self, venue_id: str, seat_id: str, unavailable: bool) -> SeatSnapshot | None:
        tracker = self.trackers.get(venue_id)
        if tracker is None or seat_id not in tracker.seats:
            return None
        tracker.set_unavailable(seat_id, unavailable)
        if not unavailable:
            self._workspace_evidence.get(venue_id, {}).pop(seat_id, None)
        snapshots = tracker.snapshots()
        self.repo.save_seat_snapshots(snapshots)
        return next(snapshot for snapshot in snapshots if snapshot.seat_id == seat_id)
