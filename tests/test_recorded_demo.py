import threading
import hashlib

import numpy as np
import pytest

from birdie.config import Timers
from birdie.models import Seat, SeatState, Venue, VenueConfig, VenueSource, VenueType
from birdie.service import BirdieService
from birdie.storage import Repository
from birdie.vision import demo


def test_reflected_person_is_excluded_but_real_person_is_counted(clock):
    venue = Venue(venue_id="v", name="Demo", area="Doha", type=VenueType.cafe,
                  lat=0, lon=0, zones=["open"], source=VenueSource.recorded)
    seats = [
        Seat(seat_id="A", venue_id="v", zone="open", polygon=[(0, 0), (.5, 0), (.5, 1), (0, 1)]),
        Seat(seat_id="B", venue_id="v", zone="open", polygon=[(.5, 0), (1, 0), (1, 1), (.5, 1)]),
    ]
    cfg = VenueConfig(venue=venue, seats=seats,
                      ignored_person_regions=[[(0, 0), (.4, 0), (.4, 1), (0, 1)]])
    detections = [
        {"label": "person", "score": .9, "box": [10, 10, 30, 90]},
        {"label": "person", "score": .9, "box": [60, 10, 80, 90]},
    ]
    svc = BirdieService(repo=Repository(":memory:"), clock=clock, venues={"v": cfg},
                        timers=Timers(hold_seconds=30, smoothing_frames=1, camera_stale_seconds=10),
                        detector=lambda image, threshold: detections, persist_venues=False)
    svc.process_frame("v", np.zeros((100, 100, 3), dtype=np.uint8))
    assert svc.state_of("v", "A") == SeatState.FREE
    assert svc.state_of("v", "B") == SeatState.OCCUPIED
    svc.upsert_seat(seats[0])
    assert svc.configs["v"].ignored_person_regions == cfg.ignored_person_regions


def test_recorded_demo_processes_frames_and_marks_decode_failures_unknown(monkeypatch):
    stop = threading.Event()

    class Service:
        configs = {"v": object()}
        trackers = {"v": object()}
        seen = []
        unknown = []

        def venue(self, _):
            return type("V", (), {"source": VenueSource.recorded})()

        def validate_recording(self, venue_id, path):
            pass

        def reset_alignment(self, venue_id):
            pass

        def process_frame(self, venue_id, frame, update_state):
            self.seen.append((venue_id, update_state))
            stop.set()

        def mark_unknown(self, venue_id):
            self.unknown.append(venue_id)

    svc = Service()
    monkeypatch.setattr(demo, "iter_clip_frames", lambda path, fps: iter([(0, np.zeros((1, 1, 3)))]))
    demo.replay_recording(svc, "v", "clip.mp4", stop)
    assert svc.seen == [("v", True)]
    assert svc.unknown == ["v"]

    stop.clear()
    def broken(path, fps):
        raise ValueError("unreadable")
    monkeypatch.setattr(demo, "iter_clip_frames", broken)
    demo.replay_recording(svc, "v", "clip.mp4", stop)
    assert svc.unknown == ["v", "v", "v"]


def test_calibration_rejects_another_recording(clock, tmp_path):
    venue = Venue(venue_id="v", name="Demo", area="Doha", type=VenueType.cafe,
                  lat=0, lon=0, zones=["open"], source=VenueSource.recorded)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"reference clip")
    cfg = VenueConfig(venue=venue, seats=[], recording_sha256=hashlib.sha256(b"reference clip").hexdigest())
    svc = BirdieService(repo=Repository(":memory:"), clock=clock, venues={"v": cfg}, persist_venues=False)
    svc.validate_recording("v", str(clip))
    clip.write_bytes(b"another camera view")
    with pytest.raises(ValueError, match="own seat and mirror calibration"):
        svc.validate_recording("v", str(clip))


def test_calibration_change_during_inference_never_reuses_old_frame(clock):
    venue = Venue(venue_id="v", name="Demo", area="Doha", type=VenueType.cafe,
                  lat=0, lon=0, zones=["open"], source=VenueSource.recorded)
    seat = Seat(seat_id="A", venue_id="v", zone="open", polygon=[(0, 0), (1, 0), (1, 1), (0, 1)])
    svc = BirdieService(repo=Repository(":memory:"), clock=clock,
                        venues={"v": VenueConfig(venue=venue, seats=[seat])},
                        timers=Timers(hold_seconds=30, smoothing_frames=1, camera_stale_seconds=10),
                        persist_venues=False)
    svc.trackers["v"].force({"A": SeatState.FREE}, emit=False)

    def detect(image, threshold):
        svc.upsert_seat(seat.model_copy(update={"polygon": [(0, 0), (.5, 0), (.5, 1), (0, 1)]}))
        return [{"label": "person", "score": .9, "box": [10, 10, 30, 90]}]

    svc._detect = detect
    svc.process_frame("v", np.zeros((100, 100, 3), dtype=np.uint8))
    assert svc.state_of("v", "A") == SeatState.UNKNOWN
