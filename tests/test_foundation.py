from datetime import timedelta

import pytest
from pydantic import ValidationError

from birdie import config
from birdie.clock import DOHA_TZ, FakeClock
from birdie.models import Seat, SeatEvent, SeatState, VenueSource
from birdie.storage import bucket_start
from birdie.venues import load_all


def test_demo_mode_default_timers():
    assert config.DEMO_MODE is True
    assert config.TIMERS.hold_seconds == 30
    assert config.TIMERS.smoothing_frames == 3
    assert config.TIMERS.camera_stale_seconds == 10
    assert config.PRODUCTION_TIMERS.hold_seconds == 30 * 60


def test_fake_clock_advances_without_sleeping():
    c = FakeClock()
    t0 = c.now()
    assert t0.tzinfo is not None
    c.advance(30)
    c.advance(minutes=1)
    assert c.now() - t0 == timedelta(seconds=90)


def test_seat_polygon_must_be_normalised():
    with pytest.raises(ValidationError):
        Seat(seat_id="A", venue_id="v", zone="open", polygon=[(0, 0), (2, 0), (1, 1)])
    Seat(seat_id="A", venue_id="v", zone="open", polygon=[(0, 0), (1, 0), (1, 1)])


def test_seat_events_roundtrip(repo, clock):
    ev = SeatEvent(ts=clock.now(), venue_id="v", seat_id="A", old_state=SeatState.FREE, new_state=SeatState.OCCUPIED)
    repo.add_seat_event(ev)
    repo.add_seat_event(ev.model_copy(update={"seat_id": "B"}), synthetic=True)
    assert repo.seat_events("v") == [ev, ev.model_copy(update={"seat_id": "B"})]
    assert repo.seat_events("v", include_synthetic=False) == [ev]
    repo.delete_synthetic_events()
    assert repo.seat_events("v") == [ev]


def test_occupancy_buckets_average(repo, clock):
    repo.record_occupancy("v", clock.now(), free=4, occupied=2, held=0)
    repo.record_occupancy("v", clock.now() + timedelta(minutes=1), free=2, occupied=4, held=0)
    [b] = repo.occupancy_buckets("v")
    assert b["free"] == 3 and b["occupied"] == 3 and b["total"] == 6
    assert b["ts"] == bucket_start(clock.now())
    assert bucket_start(clock.now().replace(minute=44)).minute == 30
    assert b["ts"].tzinfo == DOHA_TZ


def test_demo_venues_load():
    venues = load_all()
    assert set(venues) == {"nestwork-msheireb", "qnl", "qu-library", "qahwa-corner"}
    assert next(iter(venues)) == "nestwork-msheireb"  # live venue first
    for cfg in venues.values():
        assert cfg.seats, cfg.venue.venue_id
        assert all(s.zone in cfg.venue.zones for s in cfg.seats)
    assert venues["nestwork-msheireb"].venue.source == VenueSource.live
    assert all(v.venue.source == VenueSource.simulated for k, v in venues.items() if k != "nestwork-msheireb")
