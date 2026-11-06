import numpy as np

from birdie.models import Seat, SeatState, Venue, VenueConfig, VenueSource, VenueType
from birdie.service import BirdieService
from birdie.vision import render
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


# --- state machine -------------------------------------------------------------

def test_smoothing_needs_k_consecutive_frames(clock):
    m = machine(clock)
    feed(m, clock, P, 2)
    assert m.state == SeatState.FREE
    feed(m, clock, E)  # interrupted: candidate resets
    feed(m, clock, P, 2)
    assert m.state == SeatState.FREE
    [event] = feed(m, clock, P)
    assert m.state == SeatState.OCCUPIED
    assert event.old_state == SeatState.FREE and event.new_state == SeatState.OCCUPIED


def test_single_frame_flicker_is_ignored(clock):
    m = machine(clock)
    feed(m, clock, P, 3)
    assert m.state == SeatState.OCCUPIED
    feed(m, clock, E, 2)  # occlusion for two frames
    feed(m, clock, P, 1)
    assert m.state == SeatState.OCCUPIED


def test_items_stay_occupied_until_hold_time_then_held(clock):
    m = machine(clock, hold=30)
    feed(m, clock, P, 3)
    feed(m, clock, I, 3)  # person stepped away, bag on the chair
    assert m.state == SeatState.OCCUPIED
    feed(m, clock, I, 25)  # 28 s since items first seen alone
    assert m.state == SeatState.OCCUPIED
    events = feed(m, clock, I, 3)  # >= 30 s
    assert m.state == SeatState.HELD
    assert events[-1].old_state == SeatState.OCCUPIED and events[-1].new_state == SeatState.HELD


def test_hold_timer_fires_on_tick_without_frames(clock):
    m = machine(clock, hold=30)
    feed(m, clock, I, 3)
    assert m.state == SeatState.OCCUPIED
    clock.advance(40)
    event = m.tick()
    assert event and event.new_state == SeatState.HELD


def test_held_back_to_occupied_and_free(clock):
    m = machine(clock, hold=5)
    feed(m, clock, I, 10)
    assert m.state == SeatState.HELD
    feed(m, clock, P, 3)
    assert m.state == SeatState.OCCUPIED
    feed(m, clock, I, 3)
    assert m.state == SeatState.OCCUPIED  # hold timer restarted
    feed(m, clock, E, 3)
    assert m.state == SeatState.FREE


def test_person_return_resets_hold_timer(clock):
    m = machine(clock, hold=10)
    feed(m, clock, I, 8)
    feed(m, clock, P, 3)
    feed(m, clock, I, 8)
    assert m.state == SeatState.OCCUPIED


def test_tracker_emits_events_and_missing_seats_are_empty(clock):
    seats = [Seat(seat_id=s, venue_id="v", zone="open", polygon=[(0, 0), (1, 0), (1, 1)]) for s in ("A", "B")]
    got = []
    t = VenueTracker("v", seats, clock, on_event=got.append, k=1, hold_seconds=30)
    t.process({"A": P})
    assert t.state_of("A") == SeatState.OCCUPIED and t.state_of("B") == SeatState.FREE
    t.process({})
    assert t.state_of("A") == SeatState.FREE
    assert [(e.seat_id, e.new_state) for e in got] == [("A", SeatState.OCCUPIED), ("A", SeatState.FREE)]


# --- seat assignment -------------------------------------------------------------

LEFT = Seat(seat_id="L", venue_id="v", zone="open", polygon=[(0, 0), (0.5, 0), (0.5, 1), (0, 1)])
RIGHT = Seat(seat_id="R", venue_id="v", zone="open", polygon=[(0.5, 0), (1, 0), (1, 1), (0.5, 1)])
SMALL = Seat(seat_id="S", venue_id="v", zone="open", polygon=[(0.8, 0.8), (0.9, 0.8), (0.9, 0.9), (0.8, 0.9)])


def test_box_centre_inside_polygon():
    dets = [{"label": "person", "score": 0.9, "box": [10, 10, 40, 90]}]  # centre (25, 50) of 100x100
    out = assign_detections(dets, [LEFT, RIGHT], (100, 100))
    assert [d["label"] for d in out["L"]] == ["person"] and out["R"] == []


def test_fallback_to_largest_overlap_above_threshold():
    dets = [{"label": "backpack", "score": 0.9, "box": [70, 82, 86, 90]}]  # centre (78, 86) outside S
    out = assign_detections(dets, [SMALL], (100, 100))
    assert len(out["S"]) == 1  # 37.5% of the box is inside S
    dets = [{"label": "backpack", "score": 0.9, "box": [60, 60, 82, 82]}]  # under 1% inside
    out = assign_detections(dets, [SMALL], (100, 100))
    assert out["S"] == []


def test_observe_person_items_empty():
    out = observe({
        "A": [{"label": "person", "box": [0, 0, 1, 1], "score": 1}, {"label": "cup", "box": [0, 0, 1, 1], "score": 1}],
        "B": [{"label": "laptop", "box": [0, 0, 1, 1], "score": 1}],
        "C": [],
    })
    assert out == {"A": P, "B": I, "C": E}


# --- pipeline with a fake detector -------------------------------------------------

def _venue(clock, detections):
    cfg = VenueConfig(
        venue=Venue(venue_id="v", name="V", area="Doha", type=VenueType.cowork, lat=0, lon=0,
                    zones=["open"], source=VenueSource.live),
        seats=[LEFT, RIGHT],
    )
    from birdie.config import DEMO_TIMERS
    from birdie.storage import Repository

    svc = BirdieService(repo=Repository(":memory:"), clock=clock, venues={"v": cfg},
                        timers=DEMO_TIMERS, detector=lambda img, threshold: [dict(d) for d in detections],
                        persist_venues=False)
    return svc


def test_process_frame_updates_state_and_logs_events(clock):
    dets = [{"label": "person", "score": 0.9, "box": [100, 100, 200, 400]}]  # left half of 640x480
    svc = _venue(clock, dets)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    for _ in range(3):
        clock.advance(1)
        out = svc.process_frame("v", frame)
    assert out.shape == (480, 640, 3)
    assert svc.state_of("v", "L") == SeatState.OCCUPIED
    assert svc.state_of("v", "R") == SeatState.FREE
    [ev] = svc.repo.seat_events("v")
    assert ev.seat_id == "L" and ev.new_state == SeatState.OCCUPIED
    assert svc.has_frame("v")


def test_low_score_person_is_blurred_but_not_counted(clock):
    dets = [{"label": "person", "score": 0.25, "box": [100, 100, 200, 400]}]
    svc = _venue(clock, dets)
    for _ in range(3):
        clock.advance(1)
        svc.process_frame("v", np.zeros((480, 640, 3), dtype=np.uint8))
    assert svc.state_of("v", "L") == SeatState.FREE


def test_blur_changes_person_pixels_only():
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 255, (100, 100, 3), dtype=np.uint8)
    out = render.blur_people(frame, [[20, 20, 60, 60]], pad=0)
    assert not np.array_equal(out[20:60, 20:60], frame[20:60, 20:60])
    assert np.array_equal(out[80:, 80:], frame[80:, 80:])


def test_data_uri_is_in_memory_jpeg():
    uri = render.to_data_uri(np.zeros((10, 10, 3), dtype=np.uint8))
    assert uri.startswith("data:image/jpeg;base64,")


def test_seat_setup_upsert_and_delete(clock):
    svc = _venue(clock, [])
    new = Seat(seat_id="N1", venue_id="v", zone="terrace", polygon=[(0.1, 0.1), (0.2, 0.1), (0.2, 0.2), (0.1, 0.2)])
    svc.upsert_seat(new)
    assert svc.seat("v", "N1") == new
    assert "terrace" in svc.venue("v").zones
    assert svc.state_of("v", "N1") == SeatState.FREE
    svc.upsert_seat(new.model_copy(update={"has_outlet": True}))  # same id replaces
    assert [s.seat_id for s in svc.seats("v")].count("N1") == 1 and svc.seat("v", "N1").has_outlet
    assert svc.delete_seat("v", "N1") is True
    assert svc.seat("v", "N1") is None and svc.state_of("v", "N1") is None
    assert svc.delete_seat("v", "N1") is False


def test_setup_frame_needs_a_camera_frame(clock):
    svc = _venue(clock, [])
    assert svc.setup_frame("v") is None
    svc.process_frame("v", np.zeros((480, 640, 3), dtype=np.uint8))
    assert svc.setup_frame("v", [(0.1, 0.1)]).shape == (480, 640, 3)
