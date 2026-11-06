import sys
from datetime import datetime, timedelta

import pytest

from birdie.clock import DOHA_TZ, FakeClock
from birdie.config import DEMO_TIMERS
from birdie.decision import availability_at, blend_availability
from birdie.forecast import calendar as cal
from birdie.forecast.model import BaselineForecaster, ChronosForecaster, ForecastEngine, ForecasterUnavailable, load_chronos
from birdie.forecast.synthetic import generate_history, profile
from birdie.models import SeatState, Venue, VenueSource, VenueType
from birdie.service import BirdieService
from birdie.storage import Repository
from birdie.venues import load_all

# Week of 1 to 7 November 2026: Sunday 1st ... Friday 6th, Saturday 7th.
SUN = datetime(2026, 11, 1, 10, 0, tzinfo=DOHA_TZ)
THU = datetime(2026, 11, 5, 10, 0, tzinfo=DOHA_TZ)
FRI = datetime(2026, 11, 6, 10, 0, tzinfo=DOHA_TZ)
SAT = datetime(2026, 11, 7, 10, 0, tzinfo=DOHA_TZ)


# --- calendar ------------------------------------------------------------------------

def test_friday_and_saturday_are_the_weekend():
    assert cal.is_weekend(FRI) and cal.is_weekend(SAT)
    assert not cal.is_weekend(SUN) and not cal.is_weekend(THU)
    assert [cal.day_type(d) for d in (SUN, THU, FRI, SAT)] == ["weekday", "weekday", "friday", "saturday"]


def test_friday_morning_quiet_until_after_prayer():
    assert cal.is_friday_prayer_quiet(FRI.replace(hour=11))
    assert not cal.is_friday_prayer_quiet(FRI.replace(hour=14))
    assert not cal.is_friday_prayer_quiet(THU.replace(hour=11))


def test_ramadan_and_exam_flags_are_configurable():
    assert cal.is_ramadan(datetime(2026, 3, 1, tzinfo=DOHA_TZ))
    assert not cal.is_ramadan(SAT)
    assert cal.is_exam_season(datetime(2026, 12, 10, tzinfo=DOHA_TZ))
    custom = [(SAT.date(), SAT.date())]
    assert cal.is_exam_season(SAT, ranges=custom) and cal.is_ramadan(SAT, ranges=custom)
    f = cal.features(SAT)
    assert f["weekend"] and f["day_type"] == "saturday" and f["slot"] == 40


# --- synthetic history ----------------------------------------------------------------

def test_profiles_follow_the_qatar_calendar():
    # Friday morning cafe is quieter than the same hour on a weekday.
    assert profile("cafe", FRI.replace(hour=10)) < profile("cafe", THU.replace(hour=10))
    # Ramadan moves the cafe rush to the night, between iftar and suhoor.
    ramadan_day = datetime(2026, 3, 1, 13, 0, tzinfo=DOHA_TZ)
    assert profile("cafe", ramadan_day) < 0.1
    assert profile("cafe", ramadan_day.replace(hour=22)) > 0.8
    # Exam season fills the library.
    assert profile("library", THU.replace(hour=16), exam=True) > profile("library", THU.replace(hour=16), exam=False)


def test_synthetic_history_shape():
    v = Venue(venue_id="x", name="X", area="Doha", type=VenueType.library, lat=0, lon=0, source=VenueSource.simulated)
    rows = generate_history(v, 40, end=SAT, weeks=4, seed=1)
    assert len(rows) == 4 * 7 * 96
    assert rows[-1]["ts"] < SAT and all(r["synthetic"] for r in rows)
    assert all(0 <= r["occupied"] <= 40 and r["free"] == 40 - r["occupied"] for r in rows)
    assert generate_history(v, 40, end=SAT, weeks=4, seed=1) == rows  # deterministic for a seed


def test_baseline_learns_day_type_and_slot():
    v = Venue(venue_id="x", name="X", area="Doha", type=VenueType.library, lat=0, lon=0, source=VenueSource.simulated)
    hist = generate_history(v, 40, end=SAT, weeks=4, seed=1)
    m = BaselineForecaster(v.type).fit(hist)
    weekday_peak = m.predict_ratio(datetime(2026, 11, 8, 17, 0, tzinfo=DOHA_TZ))  # Sunday 17:00
    friday_morning = m.predict_ratio(datetime(2026, 11, 13, 10, 0, tzinfo=DOHA_TZ))
    assert weekday_peak > 0.6 and friday_morning < 0.05
    exam_peak = m.predict_ratio(datetime(2026, 12, 13, 17, 0, tzinfo=DOHA_TZ))  # a Sunday in exam season
    assert exam_peak > weekday_peak
    assert len(m.predict(SAT, 4)) == 4


def test_chronos_fails_gracefully(monkeypatch):
    monkeypatch.setitem(sys.modules, "chronos", None)  # import chronos -> ImportError
    with pytest.raises(ForecasterUnavailable):
        ChronosForecaster()
    assert load_chronos() is None


# --- availability blending ---------------------------------------------------------

def test_arrival_now_uses_live_count():
    a = blend_availability(venue_id="v", total=40, live_free=10, forecast_free_now=20, forecast_free_arrival=20,
                           arrival_minutes=0)
    assert a.live_weight == 1.0 and a.expected_free == 10
    assert a.low <= 10 <= a.high


def test_far_arrival_leans_on_forecast():
    a = blend_availability(venue_id="v", total=40, live_free=10, forecast_free_now=20, forecast_free_arrival=30,
                           arrival_minutes=120)
    assert a.live_weight < 0.05
    assert abs(a.expected_free - 30) < 1.0


def test_live_count_follows_forecast_trend():
    a = blend_availability(venue_id="v", total=40, live_free=10, forecast_free_now=20, forecast_free_arrival=14,
                           arrival_minutes=20)
    # live projected = 10 + (14 - 20) = 4; w = 0.5 -> 0.5 * 4 + 0.5 * 14 = 9
    assert a.expected_free == pytest.approx(9.0)
    narrow = blend_availability(venue_id="v", total=40, live_free=10, forecast_free_now=20, forecast_free_arrival=14,
                                arrival_minutes=0)
    assert (a.high - a.low) > (narrow.high - narrow.low)  # range widens with arrival time


def test_availability_is_clamped():
    a = blend_availability(venue_id="v", total=5, live_free=0, forecast_free_now=0, forecast_free_arrival=0,
                           arrival_minutes=10)
    assert a.expected_free == 0 and a.low == 0


# --- service integration: availability_at and simulator ------------------------------

@pytest.fixture
def svc():
    clock = FakeClock(datetime(2026, 11, 8, 16, 0, tzinfo=DOHA_TZ))  # Sunday afternoon
    s = BirdieService(repo=Repository(":memory:"), clock=clock, venues=load_all(), timers=DEMO_TIMERS,
                      detector=lambda *a, **k: [], persist_venues=False)
    live = s.trackers["nestwork-msheireb"]
    live.stale_seconds = None
    for machine in live.machines.values():
        machine.stale = None
    live.force({seat.seat_id: SeatState.FREE for seat in live.seats.values()}, emit=False)
    return s


def test_availability_at_uses_live_and_forecast_data(svc):
    vid = "nestwork-msheireb"
    result = svc.availability_at(vid, 10)
    assert result.live_free == len(svc.seats(vid)) > 0
    assert 0 <= result.expected_free <= result.total


def test_simulator_drives_seats_through_the_tracker(svc):
    svc.setup_simulation(backfill_hours=3)
    synthetic = svc.repo.seat_events("qnl")
    assert synthetic, "backfill writes a synthetic event log"
    assert not svc.repo.seat_events("qnl", include_synthetic=False)
    occupied = sum(1 for s in svc.snapshots("qnl") if s.state != SeatState.FREE)
    assert occupied > 0  # Sunday 16:00 at a library is busy
    for _ in range(60):
        svc.clock.advance(2)
        svc.tick()
    assert svc.repo.seat_events("qnl", include_synthetic=False), "live simulated events go through the same path"
    assert not svc.repo.seat_events("nestwork-msheireb"), "the live venue is never simulated"


def test_forecast_engine_uses_live_buckets(svc):
    eng: ForecastEngine = svc.forecast
    assert eng.model_name == "baseline"
    ts = svc.clock.now() + timedelta(minutes=30)
    assert 0.0 <= eng.ratio_at("qnl", ts) <= 1.0
    assert len(eng.typical_day("qnl", "weekday")) == 96
    svc.tick()
    eng.refit()  # live buckets fold in without errors
