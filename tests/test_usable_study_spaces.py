import numpy as np
import pytest
from fastapi.testclient import TestClient

from birdie.config import DETECTION_THRESHOLD
from birdie.api import create_app
from birdie.models import Seat, StudyTable, TableType, Venue, VenueConfig, VenueSource, VenueType
from birdie.service import BirdieService
from birdie.storage import Repository
from birdie.venues import load_venue, save_venue
from birdie.vision.seats import assign_detections, observe_evidence, workspace_evidence
from birdie.vision.state import Observation


def _layout(clock, *, private=False, chairs=True, item=None, person=None):
    seats = [
        Seat(seat_id="A", venue_id="v", zone="open", table_id="T",
             seat_polygon=[(.05, .5), (.25, .5), (.25, .95), (.05, .95)],
             workspace_polygon=[(.05, .1), (.45, .1), (.45, .45), (.05, .45)]),
        Seat(seat_id="B", venue_id="v", zone="open", table_id="T",
             seat_polygon=[(.55, .5), (.75, .5), (.75, .95), (.55, .95)],
             workspace_polygon=[(.55, .1), (.95, .1), (.95, .45), (.55, .45)]),
    ]
    table = StudyTable(
        table_id="T", table_type=TableType.private if private else TableType.shared,
        capacity=2, seat_ids=["A", "B"],
        table_polygon=[(0, 0), (1, 0), (1, .49), (0, .49)], is_shareable=not private,
    )
    venue = Venue(venue_id="v", name="Venue", area="Doha", type=VenueType.cowork,
                  lat=0, lon=0, source=VenueSource.recorded)
    cfg = VenueConfig(venue=venue, seats=seats, tables=[table])

    detections = []
    def detector(_image, threshold):
        return list(detections)

    if chairs:
        detections.extend([
            {"label": "chair", "score": .9, "box": [10, 60, 20, 80]},
            {"label": "chair", "score": .88, "box": [60, 60, 70, 80]},
        ])
    if item:
        detections.append(item)
    if person:
        detections.append(person)
    svc = BirdieService(repo=Repository(":memory:"), clock=clock,
                        venues={"v": cfg}, detector=detector, persist_venues=False)
    return svc, detections


def _sample(svc, count=3):
    for _ in range(count):
        svc.process_frame("v", np.zeros((100, 100, 3), dtype=np.uint8))


def test_shared_table_counts_only_individually_clear_workspaces(clock):
    svc, _ = _layout(clock, item={"label": "backpack", "score": .9, "box": [15, 20, 30, 40]})
    _sample(svc)

    result = svc.study_availability("v")
    seats = {seat["seat_id"]: seat for seat in result["seats"]}
    assert result["usable_study_spaces"] == 1
    assert seats["A"]["workspace_clear"] is False
    assert seats["A"]["usable_for_studying"] is False
    assert seats["B"]["workspace_clear"] is True
    assert seats["B"]["usable_for_studying"] is True


def test_missing_chair_detection_never_marks_empty_region_usable(clock):
    svc, _ = _layout(clock, chairs=False)
    # A chairless empty detection still reaches FREE in the occupancy state machine.
    _sample(svc)
    result = {seat["seat_id"]: seat for seat in svc.study_availability("v")["seats"]}
    assert result["A"]["seat_state"] == "FREE"
    assert result["A"]["workspace_clear"] is None
    assert result["A"]["availability_reason"] == "chair_not_visible"
    assert svc.study_availability("v")["usable_study_spaces"] == 0


def test_low_confidence_chair_is_not_enough_to_verify_workspace(clock):
    svc, detections = _layout(clock)
    for detection in detections:
        detection["score"] = DETECTION_THRESHOLD - .01
    proof = workspace_evidence(detections, svc.seats("v"), (100, 100))
    assert proof["A"].clear is None
    assert proof["A"].chair_detected is False


def test_ambiguous_shared_belonging_makes_both_workspaces_unknown(clock):
    svc, _ = _layout(clock, item={"label": "laptop", "score": .9, "box": [40, 20, 60, 40]})
    _sample(svc)
    result = {seat["seat_id"]: seat for seat in svc.study_availability("v")["seats"]}
    assert result["A"]["workspace_clear"] is None
    assert result["B"]["workspace_clear"] is None
    assert svc.study_availability("v")["usable_study_spaces"] == 0


def test_item_on_shared_table_outside_any_workspace_stays_unknown(clock):
    svc, detections = _layout(clock)
    detections.append({"label": "laptop", "score": .9, "box": [45, 45, 55, 48]})
    _sample(svc)
    result = {seat["seat_id"]: seat for seat in svc.study_availability("v")["seats"]}
    assert result["A"]["workspace_clear"] is None
    assert result["B"]["workspace_clear"] is None
    assert svc.study_availability("v")["usable_study_spaces"] == 0


def test_belonging_is_assigned_to_its_unique_workspace_not_neighbor():
    seats = [
        Seat(seat_id="A", venue_id="v", zone="open", table_id="T",
             polygon=[(.05, .5), (.3, .5), (.3, .95), (.05, .95)],
             workspace_polygon=[(.05, .1), (.6, .1), (.6, .55), (.05, .55)]),
        Seat(seat_id="B", venue_id="v", zone="open", table_id="T",
             polygon=[(.55, .5), (.8, .5), (.8, .95), (.55, .95)],
             workspace_polygon=[(.65, .1), (.95, .1), (.95, .45), (.65, .45)]),
    ]
    bag = {"label": "backpack", "score": .9, "box": [50, 35, 60, 55]}
    assigned = assign_detections(
        [bag], seats, (100, 100), min_overlap=.1,
        table_regions={"T": [(0, 0), (1, 0), (1, .49), (0, .49)]}
    )
    evidence = observe_evidence(assigned)
    assert {seat_id: seat.observation for seat_id, seat in evidence.items()} == {
        "A": Observation.ITEMS, "B": Observation.EMPTY,
    }


def test_private_table_is_one_space_and_closes_when_any_seat_is_occupied(clock):
    svc, detections = _layout(clock, private=True)
    _sample(svc)
    result = svc.study_availability("v")
    assert result["usable_study_spaces"] == 1
    assert result["usable_seats"] == 2

    detections.append({"label": "person", "score": .95, "box": [60, 55, 70, 80]})
    _sample(svc)
    result = svc.study_availability("v")
    assert result["usable_study_spaces"] == 0
    assert all(not seat["usable_for_studying"] for seat in result["seats"])


def test_single_person_desk_counts_as_one_study_space(clock):
    seat = Seat(
        seat_id="D1", venue_id="v", zone="open", table_id="D1",
        seat_polygon=[(.2, .5), (.4, .5), (.4, .9), (.2, .9)],
        workspace_polygon=[(.2, .1), (.4, .1), (.4, .4), (.2, .4)],
    )
    table = StudyTable(table_id="D1", table_type=TableType.single_person_desk,
                       capacity=1, seat_ids=["D1"], table_polygon=[(.1, 0), (.5, 0), (.5, .45), (.1, .45)])
    venue = Venue(venue_id="v", name="Venue", area="Doha", type=VenueType.cowork,
                  lat=0, lon=0, source=VenueSource.recorded)
    detector = lambda image, threshold: [{"label": "chair", "score": .9, "box": [25, 60, 35, 80]}]
    svc = BirdieService(repo=Repository(":memory:"), clock=clock,
                        venues={"v": VenueConfig(venue=venue, seats=[seat], tables=[table])},
                        detector=detector, persist_venues=False)
    _sample(svc)
    assert svc.study_availability("v")["usable_study_spaces"] == 1


def test_camera_failure_clears_study_space_evidence(clock):
    svc, _ = _layout(clock)
    _sample(svc)
    assert svc.study_availability("v")["usable_study_spaces"] == 2
    svc.mark_unknown("v")
    result = svc.study_availability("v")
    assert result["usable_study_spaces"] == 0
    assert all(seat["workspace_clear"] is None for seat in result["seats"])


def test_table_to_seat_mapping_survives_venue_file_restart(tmp_path):
    svc, _ = _layout(None)
    path = save_venue(svc.configs["v"], tmp_path)
    loaded = load_venue("v", tmp_path)
    assert loaded.tables[0].seat_ids == ["A", "B"]
    assert loaded.seats[0].workspace_polygon
    assert path.exists()


def test_table_mapping_rejects_seat_and_table_mismatch():
    svc, _ = _layout(None)
    cfg = svc.configs["v"].model_dump()
    cfg["tables"][0]["seat_ids"] = ["A"]
    with pytest.raises(ValueError, match="table_id does not match"):
        VenueConfig.model_validate(cfg)


def test_degenerate_workspace_polygon_is_rejected():
    with pytest.raises(ValueError, match="valid area"):
        Seat(seat_id="A", venue_id="v", zone="open",
             seat_polygon=[(0, 0), (1, 0), (1, 1)],
             workspace_polygon=[(.2, .2), (.2, .2), (.2, .2)])


def test_read_api_reports_study_spaces_and_hides_camera_geometry(clock):
    svc, _ = _layout(clock)
    _sample(svc)
    client = TestClient(create_app(svc))
    venue = client.get("/api/venues/v").json()
    assert venue["counts"]["usable_study_spaces"] == 2
    assert venue["tables"][0]["table_id"] == "T"
    assert venue["tables"][0]["seats"][0]["usable_for_studying"] is True
    assert "seat_polygon" not in venue["seats"][0]
    assert "workspace_polygon" not in venue["seats"][0]


def test_staff_table_override_is_authorized_and_persisted(clock, monkeypatch, tmp_path):
    svc, _ = _layout(clock)
    svc.venues_dir = tmp_path
    svc.persist_venues = True
    client = TestClient(create_app(svc))
    monkeypatch.setenv("BIRDIE_ADMIN_TOKEN", "test-token")
    path = "/api/venues/v/tables/T/unavailable"
    assert client.put(path, json={"unavailable": True}).status_code == 401
    response = client.put(path, json={"unavailable": True}, headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    assert response.json()["is_available_for_studying"] is False
    assert load_venue("v", tmp_path).tables[0].is_available_for_studying is False
