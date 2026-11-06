import numpy as np
import pytest

from birdie.config import DEMO_TIMERS
from birdie.models import Seat, SeatState, Venue, VenueConfig, VenueSource, VenueType
from birdie.service import BirdieService
from birdie.storage import Repository
from birdie.vision import render
from birdie.vision.chairs import auto_number, chair_candidates, natural_key
from birdie.vision.detector import KEEP_LABELS
from birdie.vision.seats import assign_detections, observe
from birdie.vision.state import Observation, SeatStateMachine, VenueTracker

P, I, E = Observation.PERSON, Observation.ITEMS, Observation.EMPTY


def machine(clock, k=3, hold=30):
    return SeatStateMachine("v", "A", clock, k=k, hold_seconds=hold)


def feed(m, clock, obs, n=1, step=1.0):
    events = []
    for _ in range(n):
        clock.advance(step)
        e = m.update(obs)
        if e:
            events.append(e)
    return events


# --- state machine: three states only ----------------------------------------------------

def test_three_states_only():
    assert [s.value for s in SeatState] == ["FREE", "OCCUPIED", "HELD"]
    assert not hasattr(Observation, "UNKNOWN")


def test_smoothing_needs_k_consecutive_frames(clock):
    m = machine(clock)
    feed(m, clock, P, 2)
    assert m.state == SeatState.FREE
    feed(m, clock, E)
    feed(m, clock, P, 2)
    assert m.state == SeatState.FREE
    [event] = feed(m, clock, P)
    assert m.state == SeatState.OCCUPIED
    assert event.old_state == SeatState.FREE and event.new_state == SeatState.OCCUPIED


def test_single_frame_flicker_is_ignored(clock):
    m = machine(clock)
    feed(m, clock, P, 3)
    feed(m, clock, E, 2)
    feed(m, clock, P, 1)
    assert m.state == SeatState.OCCUPIED


def test_items_stay_occupied_until_hold_time_then_held(clock):
    m = machine(clock, hold=30)
    feed(m, clock, P, 3)
    feed(m, clock, I, 3)
    assert m.state == SeatState.OCCUPIED
    feed(m, clock, I, 25)
    assert m.state == SeatState.OCCUPIED
    events = feed(m, clock, I, 3)
    assert m.state == SeatState.HELD
    assert events[-1].old_state == SeatState.OCCUPIED and events[-1].new_state == SeatState.HELD


def test_hold_timer_fires_on_tick_without_frames(clock):
    m = machine(clock, hold=30)
    feed(m, clock, I, 3)
    clock.advance(40)
    event = m.tick()
    assert event and event.new_state == SeatState.HELD


def test_held_back_to_occupied_and_free(clock):
    m = machine(clock, hold=5)
    feed(m, clock, I, 10)
    assert m.state == SeatState.HELD
    feed(m, clock, P, 3)
    assert m.state == SeatState.OCCUPIED
    feed(m, clock, E, 3)
    assert m.state == SeatState.FREE


def test_tracker_missing_seats_keep_their_state(clock):
    seats = [Seat(seat_id=s, venue_id="v", zone="open", polygon=[(0, 0), (1, 0), (1, 1)]) for s in ("A", "B")]
    got = []
    t = VenueTracker("v", seats, clock, on_event=got.append, k=1, hold_seconds=30)
    t.process({"A": P, "B": P})
    t.process({"A": E})  # B not observed this frame (no outline / not in view): unchanged
    assert t.state_of("A") == SeatState.FREE and t.state_of("B") == SeatState.OCCUPIED
    assert [(e.seat_id, e.new_state) for e in got] == [
        ("A", SeatState.OCCUPIED), ("B", SeatState.OCCUPIED), ("A", SeatState.FREE)]


# --- one seat per chair -------------------------------------------------------------------

def chair(x1, y1, x2, y2, score=0.8):
    return {"label": "chair", "score": score, "box": [x1, y1, x2, y2]}


def test_detector_keeps_chairs_people_and_belongings():
    assert {"chair", "person", "backpack", "laptop", "cup"} <= KEEP_LABELS


def test_each_detected_chair_becomes_its_own_outline():
    dets = [chair(400, 100, 500, 300), chair(100, 100, 200, 300), chair(102, 101, 201, 299, 0.5),  # duplicate
            chair(250, 100, 350, 300, 0.2),  # too unsure
            {"label": "person", "score": 0.9, "box": [0, 0, 50, 50]}]
    cands = chair_candidates(dets, (1000, 500), pad=0.1)
    assert len(cands) == 2  # duplicate merged, low score dropped, person ignored
    left, right = cands  # sorted left to right
    assert left["box"] == [0.1, 0.2, 0.2, 0.6] and right["box"] == [0.4, 0.2, 0.5, 0.6]
    assert left["polygon"][0] == pytest.approx((0.09, 0.16)) and left["polygon"][2] == pytest.approx((0.21, 0.64))


def test_auto_number_left_to_right_in_floor_plan_order():
    cands = [{"box": [0.1, 0, 0.2, 1]}, {"box": [0.3, 0, 0.4, 1]}, {"box": [0.5, 0, 0.6, 1]}]
    assert auto_number(cands, ["B1", "A10", "A2"]) == ["A2", "A10", "B1"]
    assert auto_number(cands, ["A1"]) == ["A1", None, None]
    assert sorted(["A10", "A2", "B1"], key=natural_key) == ["A2", "A10", "B1"]


def test_two_chairs_side_by_side_are_two_seats():
    a = Seat(seat_id="A1", venue_id="v", zone="open", polygon=[(0.1, 0.2), (0.3, 0.2), (0.3, 0.8), (0.1, 0.8)])
    b = Seat(seat_id="A2", venue_id="v", zone="open", polygon=[(0.3, 0.2), (0.5, 0.2), (0.5, 0.8), (0.3, 0.8)])
    dets = [{"label": "person", "score": 0.9, "box": [12, 25, 28, 75]},  # centre in A1
            {"label": "backpack", "score": 0.8, "box": [36, 50, 44, 70]}]  # centre in A2
    obs = observe(assign_detections(dets, [a, b], (100, 100)))
    assert obs == {"A1": P, "A2": I}


def test_fallback_to_largest_overlap_above_threshold():
    s = Seat(seat_id="S", venue_id="v", zone="seat", polygon=[(0.8, 0.8), (0.9, 0.8), (0.9, 0.9), (0.8, 0.9)])
    out = assign_detections([{"label": "backpack", "score": 0.9, "box": [70, 82, 86, 90]}], [s], (100, 100))
    assert len(out["S"]) == 1  # 37.5% of the box is inside S
    out = assign_detections([{"label": "backpack", "score": 0.9, "box": [60, 60, 82, 82]}], [s], (100, 100))
    assert out["S"] == []


# --- service: pipeline, outlines, camera online -------------------------------------------

LEFT = Seat(seat_id="L", venue_id="v", zone="open", polygon=[(0, 0), (0.5, 0), (0.5, 1), (0, 1)])
RIGHT = Seat(seat_id="R", venue_id="v", zone="open", polygon=[(0.5, 0), (1, 0), (1, 1), (0.5, 1)])
UNMAPPED = Seat(seat_id="U", venue_id="v", zone="open")


def _venue(clock, detections, seats=(LEFT, RIGHT, UNMAPPED)):
    cfg = VenueConfig(
        venue=Venue(venue_id="v", name="V", area="Doha", type=VenueType.cowork, lat=0, lon=0,
                    zones=["open"], source=VenueSource.live),
        seats=list(seats),
    )
    return BirdieService(repo=Repository(":memory:"), clock=clock, venues={"v": cfg}, timers=DEMO_TIMERS,
                         detector=lambda img, threshold: [dict(d) for d in detections], persist_venues=False)


def test_process_frame_updates_only_seats_with_outlines(clock):
    dets = [{"label": "person", "score": 0.9, "box": [100, 100, 200, 400]},  # left half of 640x480
            {"label": "chair", "score": 0.9, "box": [400, 300, 500, 400]}]  # a chair alone is not a person
    svc = _venue(clock, dets)
    for _ in range(3):
        clock.advance(1)
        out = svc.process_frame("v", np.zeros((480, 640, 3), dtype=np.uint8))
    assert out.shape == (480, 640, 3)
    assert svc.state_of("v", "L") == SeatState.OCCUPIED
    assert svc.state_of("v", "R") == SeatState.FREE
    assert svc.state_of("v", "U") == SeatState.FREE  # no outline: never observed
    [ev] = svc.repo.seat_events("v")
    assert ev.seat_id == "L" and ev.new_state == SeatState.OCCUPIED


def test_low_score_person_is_blurred_but_not_counted(clock):
    svc = _venue(clock, [{"label": "person", "score": 0.25, "box": [100, 100, 200, 400]}])
    for _ in range(3):
        clock.advance(1)
        svc.process_frame("v", np.zeros((480, 640, 3), dtype=np.uint8))
    assert svc.state_of("v", "L") == SeatState.FREE


def test_camera_offline_after_10s_and_seats_keep_last_state(clock):
    svc = _venue(clock, [{"label": "backpack", "score": 0.9, "box": [100, 100, 200, 300]}])
    assert svc.camera_online("v") is False  # no frame yet
    for _ in range(3):
        clock.advance(1)
        svc.process_frame("v", np.zeros((480, 640, 3), dtype=np.uint8))
    assert svc.camera_online("v") is True and svc.state_of("v", "L") == SeatState.OCCUPIED
    clock.advance(DEMO_TIMERS.camera_stale_seconds + 1)
    assert svc.camera_online("v") is False
    clock.advance(DEMO_TIMERS.hold_seconds)
    svc.tick()
    assert svc.state_of("v", "L") == SeatState.OCCUPIED  # frozen: the hold timer did not run while offline
    clock.advance(1)
    svc.process_frame("v", np.zeros((480, 640, 3), dtype=np.uint8))
    assert svc.camera_online("v") is True


def test_simulated_venues_have_no_camera_status(clock):
    svc = _venue(clock, [])
    svc.configs["v"] = svc.configs["v"].model_copy(
        update={"venue": svc.configs["v"].venue.model_copy(update={"source": VenueSource.simulated})})
    assert svc.camera_online("v") is None


def test_saving_outlines_never_touches_other_seat_fields(clock):
    rich = Seat(seat_id="A3", venue_id="v", zone="quiet", has_outlet=True)
    svc = _venue(clock, [], seats=[rich])
    poly = [(0.1, 0.1), (0.2, 0.1), (0.2, 0.2), (0.1, 0.2)]
    saved = svc.set_seat_polygon("v", "A3", poly)
    assert saved.polygon == poly and saved.zone == "quiet" and saved.has_outlet is True
    svc.set_seat_polygons("v", {"A3": [(0.3, 0.3), (0.4, 0.3), (0.4, 0.4)]})
    assert len(svc.seat("v", "A3").polygon) == 3
    with pytest.raises(KeyError):
        svc.set_seat_polygon("v", "Z9", poly)  # only existing (floor-plan) seats
    assert svc.clear_seat_polygon("v", "A3") is True
    assert svc.seat("v", "A3").polygon == [] and svc.seat("v", "A3").zone == "quiet"


def test_detect_chairs_snapshot_in_memory(clock):
    svc = _venue(clock, [chair(10, 10, 60, 100), chair(300, 10, 360, 100)])
    assert svc.setup_view("v") is None
    n = svc.set_setup_frame("v", np.zeros((480, 640, 3), dtype=np.uint8))
    assert n == 2 and len(svc.chair_candidates("v")) == 2
    assert svc.setup_view("v", [(0.1, 0.1)]).shape == (480, 640, 3)


def test_held_too_long_creates_one_alert_and_resolves(clock):
    svc = _venue(clock, [])
    tracker = svc.trackers["v"]
    for _ in range(3):
        clock.advance(1)
        tracker.process({"L": I, "R": E})
    clock.advance(svc.timers.hold_seconds)
    svc.tick()
    assert svc.state_of("v", "L") == SeatState.HELD
    clock.advance(svc.timers.staff_alert_seconds)
    svc.tick()
    svc.tick()
    assert [a["kind"] for a in svc.repo.alerts("v", unresolved_only=True)] == ["held_too_long"]
    for _ in range(3):
        clock.advance(1)
        tracker.process({"L": E})
    assert svc.repo.alerts("v", unresolved_only=True) == []


# --- rendering: people always blurred, boxes and outlines on top ---------------------------

def test_annotate_blurs_people_then_draws_boxes_and_outlines():
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 255, (400, 400, 3), dtype=np.uint8)
    person = {"label": "person", "score": 0.9, "box": [80, 80, 240, 240]}
    plain = render.annotate(frame, [person], show_boxes=False)
    assert plain[120:200, 120:200].std() < frame[120:200, 120:200].std() / 3  # pixelated + blurred
    assert np.array_equal(plain[320:, 320:], frame[320:, 320:])  # untouched elsewhere
    boxed = render.annotate(frame, [person], seats=[LEFT])
    assert not np.array_equal(boxed, plain)  # outline and box drawn on top


def test_blur_changes_person_pixels_only():
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 255, (100, 100, 3), dtype=np.uint8)
    out = render.blur_people(frame, [[20, 20, 60, 60]], pad=0)
    assert not np.array_equal(out[20:60, 20:60], frame[20:60, 20:60])
    assert np.array_equal(out[80:, 80:], frame[80:, 80:])


def test_seat_colours_follow_the_brief():
    assert render.STATE_COLORS[SeatState.FREE] == (0x17, 0x80, 0x4F)
    assert render.STATE_COLORS[SeatState.OCCUPIED] == (0x35, 0x3A, 0x42)
    assert render.STATE_COLORS[SeatState.HELD] == (0xD0, 0x8A, 0x1C)


def test_data_uri_is_in_memory_jpeg():
    assert render.to_data_uri(np.zeros((10, 10, 3), dtype=np.uint8)).startswith("data:image/jpeg;base64,")
