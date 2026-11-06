from fastapi.testclient import TestClient

from birdie.api import create_app, mount_mobile_web
from birdie.models import Seat, SeatState, Venue, VenueConfig, VenueSource, VenueType
from birdie.service import BirdieService
from birdie.storage import Repository


def test_public_api_reports_unknown_seats_as_not_free_and_hides_camera_polygons(clock):
    venue = Venue(
        venue_id="v", name="Venue", area="Doha", type=VenueType.cowork,
        lat=0, lon=0, zones=["open"], source=VenueSource.recorded,
    )
    seat = Seat(
        seat_id="A", venue_id="v", zone="open",
        polygon=[(0, 0), (1, 0), (1, 1)],
    )
    svc = BirdieService(
        repo=Repository(":memory:"), clock=clock,
        venues={"v": VenueConfig(venue=venue, seats=[seat])},
        detector=lambda image, threshold: [], persist_venues=False,
    )
    client = TestClient(create_app(svc))

    listed = client.get("/api/venues").json()[0]
    detail = client.get("/api/venues/v").json()
    assert listed["counts"]["free"] == 0
    assert listed["counts"]["unknown"] == 1
    assert listed["counts"]["taken"] == 0
    assert detail["seats"][0]["state"] == SeatState.UNKNOWN.value
    assert detail["seats"][0]["status"] == "unknown"
    assert "polygon" not in detail["seats"][0]
    assert client.get("/api/venues/missing").status_code == 404


def test_mobile_web_is_served_after_api_routes(clock):
    venue = Venue(
        venue_id="v", name="Venue", area="Doha", type=VenueType.cowork,
        lat=0, lon=0, zones=["open"], source=VenueSource.recorded,
    )
    svc = BirdieService(
        repo=Repository(":memory:"), clock=clock,
        venues={"v": VenueConfig(venue=venue, seats=[])}, persist_venues=False,
        detector=lambda image, threshold: [],
    )
    app = create_app(svc)
    mount_mobile_web(app)
    client = TestClient(app)
    assert "Birdie" in client.get("/").text
    assert client.get("/api/venues").status_code == 200


def test_staff_override_requires_token_and_changes_availability(clock, monkeypatch):
    venue = Venue(
        venue_id="v", name="Venue", area="Doha", type=VenueType.cowork,
        lat=0, lon=0, zones=["open"], source=VenueSource.recorded,
    )
    seat = Seat(seat_id="A", venue_id="v", zone="open")
    svc = BirdieService(
        repo=Repository(":memory:"), clock=clock,
        venues={"v": VenueConfig(venue=venue, seats=[seat])},
        detector=lambda image, threshold: [], persist_venues=False,
    )
    client = TestClient(create_app(svc))
    monkeypatch.setenv("BIRDIE_ADMIN_TOKEN", "test-token")

    response = client.put("/api/venues/v/seats/A/unavailable", json={"unavailable": True})
    assert response.status_code == 401
    response = client.put(
        "/api/venues/v/seats/A/unavailable", json={"unavailable": True},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert response.json()["state"] == SeatState.UNAVAILABLE.value
    assert svc.counts("v")[SeatState.FREE] == 0
