import pytest

from birdie.models import Seat, SeatState
from birdie.vision.seats import assign_detections, observe, observe_evidence
from birdie.vision.state import Observation, SeatStateMachine


def test_seated_person_with_small_overlap_never_makes_seat_free():
    seat = Seat(seat_id="A", venue_id="v", zone="open", polygon=[(.2, .7), (.4, .7), (.4, .9), (.2, .9)])
    assigned = assign_detections(
        [{"label": "person", "score": .9, "box": [20, 20, 40, 75]}], [seat], (100, 100)
    )
    assert observe_evidence(assigned)["A"].observation == Observation.UNKNOWN


def test_person_crossing_adjacent_seat_keeps_that_seat_unknown():
    seats = [
        Seat(seat_id="A", venue_id="v", zone="open", polygon=[(0, 0), (.5, 0), (.5, 1), (0, 1)]),
        Seat(seat_id="B", venue_id="v", zone="open", polygon=[(.5, 0), (1, 0), (1, 1), (.5, 1)]),
    ]
    assigned = assign_detections(
        [{"label": "person", "score": .9, "box": [20, 20, 60, 80]}], seats, (100, 100)
    )
    assert observe(assigned) == {"A": Observation.PERSON, "B": Observation.UNKNOWN}


def test_chair_detection_is_not_occupancy_evidence():
    seat = Seat(seat_id="A", venue_id="v", zone="open", polygon=[(.2, .7), (.4, .7), (.4, .9), (.2, .9)])
    assigned = assign_detections(
        [{"label": "chair", "score": .9, "box": [20, 20, 40, 75]}], [seat], (100, 100)
    )
    assert observe_evidence(assigned)["A"].observation == Observation.EMPTY


def test_duplicate_weak_belongings_box_does_not_hide_strong_item():
    box = [270.4, 185.3, 304.3, 224.1]
    evidence = observe_evidence({"A": [
        {"label": "handbag", "score": .495, "box": box},
        {"label": "backpack", "score": .263, "box": box.copy()},
    ]})
    assert evidence["A"].observation == Observation.ITEMS


def test_strong_belongings_remain_held_with_another_weak_item():
    evidence = observe_evidence({"A": [
        {"label": "handbag", "score": .495, "box": [0, 0, 10, 10]},
        {"label": "backpack", "score": .263, "box": [11, 0, 20, 10]},
    ]})
    assert evidence["A"].observation == Observation.ITEMS


@pytest.mark.parametrize(
    ("observation", "expected"),
    [(Observation.PERSON, SeatState.OCCUPIED), (Observation.ITEMS, SeatState.HELD)],
)
def test_free_seat_immediately_becomes_unknown_when_evidence_conflicts(clock, observation, expected):
    machine = SeatStateMachine("v", "A", clock, k=3, hold_seconds=30, initial=SeatState.FREE)
    event = machine.update(observation)
    assert (event.old_state, event.new_state) == (SeatState.FREE, SeatState.UNKNOWN)
    machine.update(observation)
    assert machine.state == SeatState.UNKNOWN
    machine.update(observation)
    assert machine.state == expected


def test_restart_does_not_promote_unconfirmed_person_to_occupied(clock):
    seat = Seat(seat_id="A", venue_id="v", zone="open")
    machine = SeatStateMachine("v", "A", clock, k=3, initial=SeatState.FREE)
    machine.update(Observation.PERSON)
    snapshot = machine.snapshot(seat)
    assert snapshot.state == SeatState.UNKNOWN and snapshot.person_detected is True
    restored = SeatStateMachine("v", "A", clock, k=3)
    restored.restore(snapshot)
    restored.tick()
    assert restored.state == SeatState.UNKNOWN


def test_item_on_shared_table_keeps_linked_seats_checking():
    seats = [
        Seat(seat_id="A", venue_id="v", zone="open", table_id="T1",
             polygon=[(0, .6), (.4, .6), (.4, 1), (0, 1)]),
        Seat(seat_id="B", venue_id="v", zone="open", table_id="T1",
             polygon=[(.6, .6), (1, .6), (1, 1), (.6, 1)]),
    ]
    table = {"T1": [(.2, .1), (.8, .1), (.8, .5), (.2, .5)]}
    item = {"label": "laptop", "score": .9, "box": [40, 20, 60, 40]}
    assigned = assign_detections([item], seats, (100, 100), table_regions=table)
    assert observe(assigned) == {"A": Observation.UNKNOWN, "B": Observation.UNKNOWN}


def test_item_on_single_seat_table_can_be_associated():
    seat = Seat(seat_id="A", venue_id="v", zone="open", table_id="T1",
                polygon=[(0, .6), (.4, .6), (.4, 1), (0, 1)])
    table = {"T1": [(.2, .1), (.8, .1), (.8, .5), (.2, .5)]}
    item = {"label": "laptop", "score": .9, "box": [40, 20, 60, 40]}
    assigned = assign_detections([item], [seat], (100, 100), table_regions=table)
    assert observe_evidence(assigned)["A"].observation == Observation.ITEMS


def test_uncertain_or_returning_person_resets_unattended_timer(clock):
    machine = SeatStateMachine("v", "A", clock, k=1, hold_seconds=30, stale_seconds=None)
    machine.update(Observation.ITEMS)
    assert machine.state == SeatState.HELD
    clock.advance(20)
    machine.update(Observation.UNKNOWN)
    assert machine.state == SeatState.UNKNOWN and machine.unattended_since is None
    clock.advance(20)
    machine.update(Observation.ITEMS)
    assert machine.state == SeatState.HELD
    machine.update(Observation.PERSON)
    assert machine.state == SeatState.OCCUPIED and machine.unattended_since is None
