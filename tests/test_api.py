"""API tests, including a contract test against web/mock.js (the shapes the mobile app was built on)."""

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from birdie.api import create_app
from birdie.clock import DOHA_TZ, FakeClock
from birdie.config import DEMO_TIMERS
from birdie.models import Seat, SeatState, VenueType
from birdie.service import BirdieService
from birdie.storage import Repository
from birdie.venues import load_all

ROOT = Path(__file__).resolve().parent.parent
MOCK_JS = ROOT / "web" / "mock.js"


@pytest.fixture
def svc():
    clock = FakeClock(datetime(2026, 11, 8, 16, 0, tzinfo=DOHA_TZ))
    detections = []
    s = BirdieService(repo=Repository(":memory:"), clock=clock, venues=load_all(), timers=DEMO_TIMERS,
                      detector=lambda img, threshold: [dict(d) for d in detections], persist_venues=False)
    s.setup_simulation(backfill_hours=0)
    s._test_detections = detections
    return s


@pytest.fixture
def client(svc):
    return TestClient(create_app(svc))


def test_list_and_detail_shapes(client):
    venues = client.get("/api/venues").json()
    assert len(venues) == 7 and venues[0]["venue_id"] == "nestwork-msheireb"
    for v in venues:
        assert "floor_plan" not in v and "seats" not in v
        assert set(v["counts"]) == {"free", "taken", "held", "total"}
        assert v["counts"]["total"] == v["counts"]["free"] + v["counts"]["taken"] + v["counts"]["held"]
    detail = client.get("/api/venues/qnl").json()
    assert detail["floor_plan"]["width"] == 362 and detail["floor_plan"]["tables"]
    seat = detail["seats"][0]
    assert list(seat) == ["seat_id", "table_id", "has_outlet", "has_window", "plan_x", "plan_y", "plan_rot",
                          "status", "since"]
    assert seat["status"] in {"free", "taken", "held"}
    assert datetime.fromisoformat(seat["since"]).tzinfo is not None
    assert client.get("/api/venues/nope").status_code == 404
    assert client.get("/api/venues").headers["cache-control"] == "no-store"


def test_camera_online_live_true_false_simulated_null(client, svc):
    by_id = {v["venue_id"]: v for v in client.get("/api/venues").json()}
    assert by_id["nestwork-msheireb"]["camera_online"] is False
    assert by_id["qnl"]["camera_online"] is None
    svc.process_frame("nestwork-msheireb", np.zeros((480, 640, 3), dtype=np.uint8))
    assert client.get("/api/venues/nestwork-msheireb").json()["camera_online"] is True


def test_live_seat_status_follows_the_camera(client, svc):
    svc.set_seat_polygon("nestwork-msheireb", "A1", [(0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0)])
    svc._test_detections.append({"label": "person", "score": 0.9, "box": [100, 100, 200, 400]})
    for _ in range(3):
        svc.clock.advance(1)
        svc.process_frame("nestwork-msheireb", np.zeros((480, 640, 3), dtype=np.uint8))
    seats = {s["seat_id"]: s for s in client.get("/api/venues/nestwork-msheireb").json()["seats"]}
    assert seats["A1"]["status"] == "taken" and seats["A2"]["status"] == "free"
    counts = next(v for v in client.get("/api/venues").json() if v["venue_id"] == "nestwork-msheireb")["counts"]
    assert counts["taken"] == 1


def test_status_mapping_includes_held(svc, client):
    vid = "nestwork-msheireb"
    tracker = svc.trackers[vid]
    tracker.force({"A1": SeatState.HELD, "A2": SeatState.OCCUPIED})
    seats = {s["seat_id"]: s["status"] for s in client.get(f"/api/venues/{vid}").json()["seats"]}
    assert seats["A1"] == "held" and seats["A2"] == "taken"


def test_venues_cover_every_category_and_study_rooms_simulate(svc):
    types = {v.type for v in svc.venues()}
    assert types == {VenueType.library, VenueType.cafe, VenueType.cowork, VenueType.study_room}
    for _ in range(5):
        svc.clock.advance(2)
        svc.tick()  # simulator and forecast handle study rooms


def test_labelling_seats_json_still_loads():
    s = Seat.model_validate({"seat_id": "S01", "venue_id": "clip", "zone": "seat",
                             "polygon": [[0.1, 0.1], [0.2, 0.1], [0.2, 0.2], [0.1, 0.2]]})
    assert s.table_id is None and s.plan_x is None and not s.has_window


# --- contract test against web/mock.js ---------------------------------------------------

def _mock_data() -> dict:
    script = f"""
      global.window = global;
      require({json.dumps(str(MOCK_JS))});
      (async () => {{
        const venues = await window.BirdieMock.venues();
        const details = {{}};
        for (const v of venues) details[v.venue_id] = await window.BirdieMock.venue(v.venue_id);
        process.stdout.write(JSON.stringify({{venues, details}}));
        process.exit(0);
      }})();
    """
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout)


def _type_name(v) -> str:
    return "number" if isinstance(v, (int, float)) and not isinstance(v, bool) else type(v).__name__


def _shape(obj):
    """Keys and value types, recursively (lists: shape of the first element)."""
    if isinstance(obj, dict):
        return {k: _shape(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_shape(obj[0])] if obj else []
    return _type_name(obj)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is needed to run web/mock.js")
def test_api_matches_mock_js_shapes(client):
    mock = _mock_data()
    api_venues = client.get("/api/venues").json()
    assert {v["venue_id"] for v in api_venues} == {v["venue_id"] for v in mock["venues"]}

    m_summary = mock["venues"][0]
    a_summary = next(v for v in api_venues if v["venue_id"] == m_summary["venue_id"])
    assert set(a_summary) == set(m_summary) | {"camera_online"}
    assert _shape({k: a_summary[k] for k in m_summary}) == _shape(m_summary)

    for vid, m_detail in mock["details"].items():
        a_detail = client.get(f"/api/venues/{vid}").json()
        assert set(a_detail) == set(m_detail) | {"camera_online"}, vid
        assert list(a_detail["seats"][0]) == list(m_detail["seats"][0]), vid
        assert _shape(a_detail["seats"][0]) == _shape(m_detail["seats"][0]), vid
        assert set(a_detail["floor_plan"]) == set(m_detail["floor_plan"]), vid
        a_tables = {t["table_id"]: t for t in a_detail["floor_plan"]["tables"]}
        m_tables = {t["table_id"]: t for t in m_detail["floor_plan"]["tables"]}
        if vid == "nestwork-msheireb":
            continue  # placeholder plan until the real room is sketched
        assert a_tables == m_tables, vid
        assert a_detail["floor_plan"]["fixtures"] == m_detail["floor_plan"]["fixtures"], vid
        a_pos = {s["seat_id"]: (s["table_id"], s["plan_x"], s["plan_y"], s["plan_rot"], s["has_outlet"], s["has_window"])
                 for s in a_detail["seats"]}
        m_pos = {s["seat_id"]: (s["table_id"], s["plan_x"], s["plan_y"], s["plan_rot"], s["has_outlet"], s["has_window"])
                 for s in m_detail["seats"]}
        assert set(a_pos) == set(m_pos), vid
        for sid, (tid, x, y, rot, outlet, window) in m_pos.items():
            at = a_pos[sid]
            assert at[0] == tid and at[4:] == (outlet, window), (vid, sid)
            assert at[1:4] == pytest.approx((x, y, rot), abs=0.11), (vid, sid)
