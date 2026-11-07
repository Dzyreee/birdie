import cv2
import numpy as np

from birdie.config import BELONGINGS_THRESHOLD, DEMO_TIMERS
from birdie.models import Seat, SeatState, Venue, VenueConfig, VenueSource, VenueType
from birdie.service import BirdieService
from birdie.storage import Repository
from birdie.vision.motion import FrameAligner, warp_polygon


def textured(seed=0, size=(480, 640)):
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 255, (size[0] // 8, size[1] // 8, 3), dtype=np.uint8)
    img = cv2.resize(img, (size[1], size[0]), interpolation=cv2.INTER_CUBIC)
    return cv2.GaussianBlur(img, (0, 0), 1.2)


def shifted(img, dx, dy):
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]), borderMode=cv2.BORDER_REFLECT)


def test_aligner_follows_a_camera_pan():
    ref = textured()
    al = FrameAligner()
    assert np.allclose(al.update(ref), np.eye(3))  # first frame is the reference
    h = al.update(shifted(ref, 32, 24))  # camera drifted: the picture moved by (32, 24) px
    box = [(0.25, 0.25), (0.5, 0.25), (0.5, 0.5), (0.25, 0.5)]
    out = warp_polygon(box, h)
    assert np.allclose(out[0], (0.25 + 32 / 640, 0.25 + 24 / 480), atol=0.01)
    assert al.last_inliers > 50


def test_aligner_keeps_last_transform_when_a_frame_cannot_be_matched():
    ref = textured()
    al = FrameAligner()
    al.update(ref)
    good = al.update(shifted(ref, 16, 0))
    blank = np.zeros_like(ref)
    assert np.allclose(al.update(blank), good)  # no features: reuse the last good transform
    al.reset()
    assert not al.has_reference and np.allclose(al.update(blank), np.eye(3))


def _service(clock, detections, polygon):
    cfg = VenueConfig(
        venue=Venue(venue_id="v", name="V", area="Doha", type=VenueType.cowork, lat=0, lon=0, zones=["open"],
                    source=VenueSource.live),
        seats=[Seat(seat_id="A1", venue_id="v", zone="open", polygon=polygon)],
    )
    return BirdieService(repo=Repository(":memory:"), clock=clock, venues={"v": cfg}, timers=DEMO_TIMERS,
                         detector=lambda img, threshold: [dict(d) for d in detections], persist_venues=False)


def test_outlines_move_with_the_picture_so_a_drifting_camera_keeps_the_seat(clock):
    ref = textured()
    # The bag is at the same place in the room; in the second frame the camera has drifted right by 64 px,
    # so the bag appears 64 px further left in the picture: outside the fixed outline, inside the moved one.
    bag_ref = {"label": "backpack", "score": 0.3, "box": [250.0, 200.0, 300.0, 250.0]}
    bag_moved = {"label": "backpack", "score": 0.3, "box": [186.0, 200.0, 236.0, 250.0]}
    outline = [(0.35, 0.35), (0.55, 0.35), (0.55, 0.65), (0.35, 0.65)]
    frames = [(ref, bag_ref), (shifted(ref, -64, 0), bag_moved)]
    svc = _venue_run(clock, outline, frames)
    assert svc.state_of("v", "A1") == SeatState.OCCUPIED  # the bag stayed in the seat's outline


def _venue_run(clock, outline, frames):
    current = []
    svc = _service(clock, current, outline)
    svc._detect = lambda img, threshold: [dict(d) for d in current]
    for _ in range(2):  # repeat so 3-frame smoothing is reached
        svc.reset_alignment("v")
        for img, det in frames:
            current[:] = [det]
            clock.advance(1)
            svc.process_frame("v", img)
    return svc


def test_belongings_count_from_a_low_score_but_people_do_not(clock):
    assert BELONGINGS_THRESHOLD <= 0.2
    det = [{"label": "backpack", "score": 0.2, "box": [100, 100, 200, 200]}]
    svc = _service(clock, det, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
    for _ in range(3):
        clock.advance(1)
        svc.process_frame("v", np.zeros((480, 640, 3), dtype=np.uint8))
    assert svc.state_of("v", "A1") == SeatState.OCCUPIED  # a 0.2 backpack counts as belongings
    person = [{"label": "person", "score": 0.3, "box": [100, 100, 200, 200]}]
    svc2 = _service(clock, person, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
    for _ in range(3):
        clock.advance(1)
        svc2.process_frame("v", np.zeros((480, 640, 3), dtype=np.uint8))
    assert svc2.state_of("v", "A1") == SeatState.FREE  # a 0.3 person does not
