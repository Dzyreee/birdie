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
    assert set(venues) == {"nestwork-msheireb", "corniche-cup"}  # the two recorded clips, nothing simulated
    for cfg in venues.values():
        assert cfg.venue.source == VenueSource.recorded
        assert cfg.seats and cfg.recording_sha256 and len(cfg.recording_sha256) == 64
        assert all(s.zone in cfg.venue.zones for s in cfg.seats)
        assert len({s.seat_id for s in cfg.seats}) == len(cfg.seats)
    assert len(venues["nestwork-msheireb"].seats) == 7
    assert venues["nestwork-msheireb"].recording_sha256 != venues["corniche-cup"].recording_sha256


def test_corniche_cup_is_a_recorded_venue_in_the_same_format_as_nestwork():
    venues = load_all()
    nest, cup = venues["nestwork-msheireb"], venues["corniche-cup"]
    assert cup.recording_sha256 and len(cup.recording_sha256) == 64  # the clip is pinned, like Nestwork's
    assert cup.stabilize_camera and cup.belongings_threshold == 0.15  # tuned for its hand-held clip
    assert nest.stabilize_camera and nest.belongings_threshold == 0.3  # its clip is hand-held too
    assert len(cup.seats) == 8 and all(len(s.seat_polygon) >= 3 and s.table_id for s in cup.seats)
    plan_tables = {t["table_id"] for t in cup.venue.floor_plan["tables"]}
    assert {s.table_id for s in cup.seats} == plan_tables == {t.table_id for t in cup.tables}
    assert all(s.plan_x is not None and s.plan_y is not None for s in cup.seats)


def test_a_clip_finds_its_own_venue_by_hash(tmp_path):
    import hashlib

    from birdie.service import BirdieService
    from birdie.storage import Repository

    svc = BirdieService(repo=Repository(":memory:"), venues=load_all(), detector=lambda *a, **k: [],
                        persist_venues=False)
    clip = tmp_path / "x.mp4"
    clip.write_bytes(b"not really a video")
    assert svc.venue_for_clip(str(clip)) is None  # an unknown clip matches no venue
    digest = hashlib.sha256(clip.read_bytes()).hexdigest()
    svc.configs["corniche-cup"] = svc.configs["corniche-cup"].model_copy(update={"recording_sha256": digest})
    assert svc.venue_for_clip(str(clip)) == "corniche-cup"
