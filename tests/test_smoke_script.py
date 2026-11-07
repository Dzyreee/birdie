"""The live smoke test's contract checks must accept what the real API returns (checked offline)."""

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from birdie.api import create_app
from birdie.clock import DOHA_TZ, FakeClock
from birdie.config import DEMO_TIMERS
from birdie.service import BirdieService
from birdie.storage import Repository
from birdie.venues import load_all


def _load_smoke():
    path = Path(__file__).resolve().parent.parent / "scripts" / "smoke_test.py"
    spec = importlib.util.spec_from_file_location("smoke_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["smoke_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def api():
    clock = FakeClock(datetime(2026, 11, 8, 16, 0, tzinfo=DOHA_TZ))
    svc = BirdieService(repo=Repository(":memory:"), clock=clock, venues=load_all(), timers=DEMO_TIMERS,
                        detector=lambda *a, **k: [], persist_venues=False)
    svc.setup_simulation(backfill_hours=0)
    return TestClient(create_app(svc))


def test_smoke_checks_accept_the_real_api(api):
    smoke = _load_smoke()
    venues = api.get("/api/venues").json()
    assert {v["venue_id"] for v in venues} == smoke.EXPECTED_VENUES
    for v in venues:
        assert smoke.check_venue_summary(v) == [], v["venue_id"]
        assert smoke.check_seats(api.get(f"/api/venues/{v['venue_id']}").json()) == [], v["venue_id"]


def test_smoke_checks_catch_a_broken_response(api):
    smoke = _load_smoke()
    detail = api.get("/api/venues/corniche-cup").json()
    detail["seats"][0]["status"] = "mystery"
    assert any("status" in p for p in smoke.check_seats(detail))
    detail = api.get("/api/venues/corniche-cup").json()
    detail["floor_plan"] = None
    assert smoke.check_seats(detail)
    summary = api.get("/api/venues").json()[0]
    summary["counts"]["total"] += 1  # counts that don't add up must be caught
    assert smoke.check_venue_summary(summary)
