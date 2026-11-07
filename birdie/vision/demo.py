"""Replay a configured recording in the background for the customer demo."""

from __future__ import annotations

import logging
import threading
import time

from pathlib import Path

from birdie.config import ROOT_DIR, TARGET_FPS
from birdie.models import VenueSource
from birdie.service import BirdieService
from birdie.vision.clip import iter_clip_frames

log = logging.getLogger(__name__)


def replay_recording(svc: BirdieService, venue_id: str, path: str, stop: threading.Event) -> None:
    """Repeat a recording at its source timestamps until stopped or decoding fails."""
    svc.recorded_demo_status = {"state": "starting", "venue_id": venue_id}
    try:
        if venue_id not in svc.configs or svc.venue(venue_id).source != VenueSource.recorded:
            raise ValueError(f"{venue_id!r} is not a recorded-demo venue")
        svc.validate_recording(venue_id, path)
        svc.mark_unknown(venue_id)  # Discard persisted states/timers from an earlier recording session.
        while not stop.is_set():
            svc.reset_alignment(venue_id)  # first frame of each pass = reference for the outlines (stabilised venues)
            start = time.monotonic()
            for timestamp, frame in iter_clip_frames(path, fps=TARGET_FPS):
                if stop.is_set():
                    return
                svc.process_frame(venue_id, frame, update_state=True)
                svc.recorded_demo_status = {"state": "running", "venue_id": venue_id,
                                            "video_time_seconds": round(timestamp, 2)}
                if stop.wait(max(0.0, start + timestamp + 1.0 / TARGET_FPS - time.monotonic())):
                    return
    except Exception:
        if venue_id in svc.trackers:
            svc.mark_unknown(venue_id)
        svc.recorded_demo_status = {"state": "error", "venue_id": venue_id}
        log.exception("Recorded demo stopped; availability is checking")


def start_recorded_demo(svc: BirdieService, venue_id: str, path: str) -> threading.Event:
    stop = threading.Event()
    threading.Thread(
        target=replay_recording, args=(svc, venue_id, path, stop),
        daemon=True, name="recorded-demo",
    ).start()
    return stop


def demo_clip_path(venue_id: str) -> Path:
    return ROOT_DIR / "demo_clips" / f"{venue_id}.mp4"


def start_for_venue(svc: BirdieService, venue_id: str) -> bool:
    """Replay demo_clips/<venue_id>.mp4 for a recorded venue if that file is on the Space."""
    path = demo_clip_path(venue_id)
    if venue_id not in svc.configs or svc.venue(venue_id).source != VenueSource.recorded or not path.is_file():
        return False
    pause_for_venue(svc, venue_id)
    svc.demo_stops[venue_id] = start_recorded_demo(svc, venue_id, str(path))
    return True


def pause_for_venue(svc: BirdieService, venue_id: str) -> None:
    """Stop a venue's replay (for example while the console plays an uploaded clip into it)."""
    stop = svc.demo_stops.pop(venue_id, None)
    if stop is not None:
        stop.set()
