import numpy as np
import pytest

from birdie.models import Seat, SeatState, Venue, VenueConfig, VenueSource, VenueType
from birdie.service import BirdieService
from birdie.vision import render
from birdie.vision.detector import KEEP_LABELS
from birdie.vision.seats import assign_detections, observe, observe_evidence
from birdie.vision.state import Observation, SeatStateMachine, VenueTracker

P, I, E = Observation.PERSON, Observation.ITEMS, Observation.EMPTY


def machine(clock, k=3, hold=30):
    return SeatStateMachine("v", "A", clock, k=k, hold_seconds=hold, initial=SeatState.FREE, stale_seconds=None)


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
    assert m.state == SeatState.UNKNOWN
    feed(m, clock, E)  # interrupted: candidate resets
    feed(m, clock, P, 2)
    assert m.state == SeatState.UNKNOWN
    [event] = feed(m, clock, P)
    assert m.state == SeatState.OCCUPIED
    assert event.old_state == SeatState.UNKNOWN and event.new_state == SeatState.OCCUPIED


def test_single_frame_flicker_is_ignored(clock):
    m = machine(clock)
    feed(m, clock, P, 3)
    assert m.state == SeatState.OCCUPIED
    feed(m, clock, E, 2)  # occlusion for two frames
    feed(m, clock, P, 1)
    assert m.state == SeatState.OCCUPIED


def test_belongings_start_held_timer_after_smoothing(clock):
    m = machine(clock, hold=30)
    feed(m, clock, P, 3)
    feed(m, clock, I, 3)
    assert m.state == SeatState.HELD
    snap = m.snapshot(Seat(seat_id="A", venue_id="v", zone="open"))
    assert snap.unattended_since is not None
    assert snap.grace_period_remaining_seconds == 28


def test_hold_timer_fires_on_tick_without_frames(clock):
    m = machine(clock, hold=30)
    feed(m, clock, I, 3)
    assert m.state == SeatState.HELD
    clock.advance(28)
    event = m.tick()
    assert event and event.new_state == SeatState.REVIEW_REQUIRED


def test_held_back_to_occupied_and_free(clock):
    m = machine(clock, hold=5)
    feed(m, clock, I, 3)
    assert m.state == SeatState.HELD
    feed(m, clock, P, 3)
    assert m.state == SeatState.OCCUPIED
    feed(m, clock, I, 3)
    assert m.state == SeatState.HELD  # new unattended period starts
    feed(m, clock, E, 3)
    assert m.state == SeatState.FREE


def test_person_return_resets_hold_timer(clock):
    m = machine(clock, hold=10)
    feed(m, clock, I, 3)
    feed(m, clock, P, 3)
    assert m.state == SeatState.OCCUPIED and m.unattended_since is None
    feed(m, clock, I, 3)
    assert m.state == SeatState.HELD


def test_unattended_timer_continues_after_process_restore(clock):
    m = machine(clock, hold=30)
    feed(m, clock, I, 3)
    snapshot = m.snapshot(Seat(seat_id="A", venue_id="v", zone="open"))
    restored = SeatStateMachine("v", "A", clock, k=3, hold_seconds=30, stale_seconds=None)
    restored.restore(snapshot)
    clock.advance(28)
    event = restored.tick()
    assert event and event.new_state == SeatState.REVIEW_REQUIRED


def test_service_restores_hold_timestamp_from_repository(clock):
    detections = [{"label": "backpack", "score": .9, "box": [100, 100, 200, 300]}]
    first = _venue(clock, detections)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    for _ in range(3):
        clock.advance(1)
        first.process_frame("v", frame)
    assert first.state_of("v", "L") == SeatState.HELD

    restarted = BirdieService(
        repo=first.repo, clock=clock, venues=first.configs, timers=first.timers,
        detector=first._detect, persist_venues=False,
    )
    for _ in range(14):
        clock.advance(2)
        restarted.process_frame("v", frame)
    assert restarted.state_of("v", "L") == SeatState.REVIEW_REQUIRED


def test_tracker_emits_events_and_missing_seats_are_unknown(clock):
    seats = [Seat(seat_id=s, venue_id="v", zone="open", polygon=[(0, 0), (1, 0), (1, 1)]) for s in ("A", "B")]
    got = []
    t = VenueTracker("v", seats, clock, on_event=got.append, k=1, hold_seconds=30)
    t.process({"A": P})
    assert t.state_of("A") == SeatState.OCCUPIED and t.state_of("B") == SeatState.UNKNOWN
    t.process({})
    assert t.state_of("A") == SeatState.UNKNOWN
    assert [(e.seat_id, e.new_state) for e in got] == [("A", SeatState.OCCUPIED), ("A", SeatState.UNKNOWN)]


def test_new_seat_needs_stable_empty_evidence_before_free(clock):
    m = SeatStateMachine("v", "A", clock, k=3, stale_seconds=None)
    feed(m, clock, E, 2)
    assert m.state == SeatState.UNKNOWN
    feed(m, clock, E)
    assert m.state == SeatState.FREE


def test_stale_camera_feed_expires_known_state(clock):
    m = SeatStateMachine("v", "A", clock, k=1, initial=SeatState.FREE, stale_seconds=5)
    feed(m, clock, P)
    clock.advance(5)
    event = m.tick()
    assert event and event.new_state == SeatState.UNKNOWN
    assert m.state == SeatState.UNKNOWN


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
    assert observe_evidence(out)["S"].observation == Observation.UNKNOWN


def test_observe_person_items_empty():
    out = observe({
        "A": [{"label": "person", "box": [0, 0, 1, 1], "score": 1}, {"label": "cup", "box": [0, 0, 1, 1], "score": 1}],
        "B": [{"label": "laptop", "box": [0, 0, 1, 1], "score": 1}],
        "C": [],
    })
    assert out == {"A": P, "B": I, "C": E}


def test_weak_person_detection_prevents_bag_from_being_marked_held():
    evidence = observe_evidence({"A": [
        {"label": "person", "score": .25, "box": [0, 0, 1, 1]},
        {"label": "backpack", "score": .9, "box": [0, 0, 1, 1]},
    ]})
    assert evidence["A"].observation == Observation.UNKNOWN


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
    assert {(ev.seat_id, ev.new_state) for ev in svc.repo.seat_events("v")} == {
        ("L", SeatState.OCCUPIED), ("R", SeatState.FREE)
    }


def test_low_score_person_makes_seat_unknown_not_free(clock):
    dets = [{"label": "person", "score": 0.25, "box": [100, 100, 200, 400]}]
    svc = _venue(clock, dets)
    for _ in range(3):
        clock.advance(1)
        svc.process_frame("v", np.zeros((480, 640, 3), dtype=np.uint8))
    assert svc.state_of("v", "L") == SeatState.UNKNOWN


def test_annotate_keeps_frame_unblurred_without_overlays():
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 255, (100, 100, 3), dtype=np.uint8)
    out = render.annotate(frame, [])
    assert np.array_equal(out, frame)


def test_annotate_draws_detector_boxes_without_a_seat_layout():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    out = render.annotate(frame, [{"label": "chair", "score": 0.9, "box": [20, 20, 80, 80]}])
    assert np.any(out[18:82, 18:82])
    assert not np.any(out[:10, :10])


def test_seat_calibration_draws_normalized_regions():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    seat = Seat(
        seat_id="S01", venue_id="v", zone="open",
        polygon=[(0.1, 0.1), (1.0, 0.1), (1.0, 1.0), (0.1, 1.0)],
    )
    out = render.draw_seat_calibration(frame, [seat], [(1.0, 1.0)])
    assert out.shape == frame.shape
    assert np.any(out != frame)


def test_detector_keeps_chairs_people_and_belongings():
    assert {"chair", "person", "backpack", "laptop"} <= KEEP_LABELS


def test_data_uri_is_in_memory_jpeg():
    uri = render.to_data_uri(np.zeros((10, 10, 3), dtype=np.uint8))
    assert uri.startswith("data:image/jpeg;base64,")


def test_seat_config_upsert_and_delete(clock):
    svc = _venue(clock, [])
    new = Seat(seat_id="N1", venue_id="v", zone="terrace", polygon=[(0.1, 0.1), (0.2, 0.1), (0.2, 0.2), (0.1, 0.2)])
    svc.upsert_seat(new)
    assert svc.seat("v", "N1") == new
    assert "terrace" in svc.venue("v").zones
    assert svc.state_of("v", "N1") == SeatState.UNKNOWN
    svc.upsert_seat(new.model_copy(update={"has_outlet": True}))  # same id replaces
    assert [s.seat_id for s in svc.seats("v")].count("N1") == 1 and svc.seat("v", "N1").has_outlet
    assert svc.delete_seat("v", "N1") is True
    assert svc.seat("v", "N1") is None and svc.state_of("v", "N1") is None
    assert svc.delete_seat("v", "N1") is False


def test_video_preview_does_not_update_seat_states(clock):
    svc = _venue(clock, [])
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    svc.process_frame(None, frame, update_state=False)
    assert all(s.state == SeatState.UNKNOWN for s in svc.snapshots("v"))


def test_held_too_long_creates_one_alert_and_resolves(clock):
    svc = _venue(clock, [])
    tracker = svc.trackers["v"]
    for _ in range(3):
        clock.advance(1)
        tracker.process({"L": I, "R": E})
    assert svc.state_of("v", "L") == SeatState.HELD
    while (clock.now() - tracker.machines["L"].unattended_since).total_seconds() < svc.timers.hold_seconds:
        clock.advance(2)
        tracker.process({"L": I, "R": E})
    svc.tick()
    assert svc.state_of("v", "L") == SeatState.REVIEW_REQUIRED
    alerts = svc.repo.alerts("v", unresolved_only=True)
    assert [a["kind"] for a in alerts] == ["review_required"]
    tracker.process({"L": Observation.UNKNOWN, "R": E})
    assert len(svc.repo.alerts("v", unresolved_only=True)) == 1
    for _ in range(3):
        clock.advance(1)
        tracker.process({"L": E, "R": E})
    assert svc.repo.alerts("v", unresolved_only=True) == []


def test_unavailable_override_needs_fresh_evidence_after_enable(clock):
    m = machine(clock, k=1)
    m.set_unavailable(True)
    feed(m, clock, E, 3)
    assert m.state == SeatState.UNAVAILABLE
    m.set_unavailable(False)
    assert m.state == SeatState.UNKNOWN
    feed(m, clock, E)
    assert m.state == SeatState.FREE


def test_overlapping_seat_regions_make_evidence_unknown():
    overlapping = [
        Seat(seat_id="A", venue_id="v", zone="open", polygon=[(0, 0), (.7, 0), (.7, 1), (0, 1)]),
        Seat(seat_id="B", venue_id="v", zone="open", polygon=[(.3, 0), (1, 0), (1, 1), (.3, 1)]),
    ]
    assigned = assign_detections(
        [{"label": "person", "score": .9, "box": [40, 20, 60, 80]}], overlapping, (100, 100)
    )
    assert observe(assigned) == {"A": Observation.UNKNOWN, "B": Observation.UNKNOWN}


def test_camera_failure_never_counts_unknown_seat_as_free(clock):
    svc = _venue(clock, [])
    svc.process_frame("v", np.zeros((480, 640, 3), dtype=np.uint8))
    svc.mark_unknown("v")
    assert svc.counts("v")[SeatState.FREE] == 0
    assert svc.counts("v")[SeatState.UNKNOWN] == 2


def test_invalid_image_dimensions_invalidate_previous_free_state(clock):
    svc = _venue(clock, [])
    svc.trackers["v"].force({"L": SeatState.FREE}, emit=False)
    with pytest.raises(ValueError, match="frame"):
        svc.process_frame("v", np.zeros((480, 640), dtype=np.uint8))
    assert svc.state_of("v", "L") == SeatState.UNKNOWN
