from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from birdie.analytics import occupancy_by_hour, peak_hours, seat_intervals, venue_dashboard
from birdie.clock import DOHA_TZ
from birdie.decision import WEIGHTS, focus_score, recommend
from birdie.models import (
    Query,
    Seat,
    SeatEvent,
    SeatSnapshot,
    SeatState,
    Venue,
    VenueSource,
    VenueType,
)
from birdie.storage import Repository

NOW = datetime(2026, 11, 8, 16, 0, tzinfo=DOHA_TZ)


def venue(vid, vtype=VenueType.library, area="Education City", noise=40.0, zones=("quiet", "open"),
          lat=25.3157, lon=51.4394, source=VenueSource.simulated):
    return Venue(venue_id=vid, name=vid.title(), area=area, type=vtype, lat=lat, lon=lon, zones=list(zones),
                 source=source, noise_db=noise)


@dataclass
class FakeData:
    """A minimal LiveData: seat states and forecasts are set directly."""

    venue_list: list[Venue]
    states: dict[str, list[tuple[str, str, bool, SeatState]]]  # vid -> [(seat_id, zone, outlet, state)]
    ratios: dict[str, float] = field(default_factory=dict)  # vid -> forecast ratio (flat)
    trend: dict[str, float] = field(default_factory=dict)  # vid -> forecast change per 30 min

    def now(self):
        return NOW

    def venues(self):
        return self.venue_list

    def venue(self, vid):
        return next(v for v in self.venue_list if v.venue_id == vid)

    def seats(self, vid):
        return [Seat(seat_id=s, venue_id=vid, zone=z, has_outlet=o) for s, z, o, _ in self.states[vid]]

    def snapshots(self, vid):
        return [SeatSnapshot(venue_id=vid, seat_id=s, zone=z, has_outlet=o, state=st, since=NOW, updated_at=NOW)
                for s, z, o, st in self.states[vid]]

    def forecast_ratio(self, vid, ts):
        minutes = (ts - NOW).total_seconds() / 60
        return min(1.0, max(0.0, self.ratios.get(vid, 0.5) + self.trend.get(vid, 0.0) * minutes / 30))


def seats(n_free, n_taken, zone="open", outlet_every=0):
    out = []
    for i in range(n_free + n_taken):
        state = SeatState.FREE if i < n_free else SeatState.OCCUPIED
        out.append((f"S{i}", zone, bool(outlet_every and i % outlet_every == 0), state))
    return out


# --- focus score ---------------------------------------------------------------------

def test_focus_score_bounds_and_breakdown_sum():
    best = FakeData([venue("a", noise=30)], {"a": seats(10, 0, outlet_every=1)}, ratios={"a": 0.5}, trend={"a": -0.5})
    worst = FakeData([venue("b", noise=80)], {"b": seats(0, 10)}, ratios={"b": 0.5}, trend={"b": 0.5})
    fb, fw = focus_score(best, "a", 0), focus_score(worst, "b", 0)
    assert fb.score == 100 and fw.score == 0
    for f in (fb, fw):
        assert [p.key for p in f.parts] == ["free", "noise", "outlets", "trend"]
        assert [p.weight for p in f.parts] == [WEIGHTS[k] for k in ("free", "noise", "outlets", "trend")] == [40, 25, 20, 15]
        assert abs(sum(p.points for p in f.parts) - f.score) <= 1
        assert all(0 <= p.points <= p.weight for p in f.parts)


def test_focus_score_prefers_quiet_emptying_venues():
    data = FakeData(
        [venue("quiet", noise=38), venue("loud", noise=65)],
        {"quiet": seats(5, 5, outlet_every=2), "loud": seats(5, 5, outlet_every=2)},
        ratios={"quiet": 0.5, "loud": 0.5},
        trend={"quiet": -0.1, "loud": 0.1},
    )
    q, loud = focus_score(data, "quiet", 15), focus_score(data, "loud", 15)
    assert q.score > loud.score
    assert q.trend_label == "emptying" and loud.trend_label == "filling up"


def test_free_seats_count_as_available_outlets():
    data = FakeData([venue("a")], {"a": seats(2, 0, outlet_every=1)}, ratios={"a": 0.0})
    result = focus_score(data, "a", 0)
    assert result.free_outlets == 2


# --- recommend -----------------------------------------------------------------------

def city():
    return FakeData(
        [
            venue("qnl", noise=40, zones=("quiet", "open")),
            venue("cafe", VenueType.cafe, area="Lusail", noise=62, zones=("indoor", "terrace"), lat=25.42, lon=51.49),
            venue("cowork", VenueType.cowork, area="Msheireb, Doha", noise=52, zones=("open",), lat=25.2867, lon=51.5265),
        ],
        {
            "qnl": seats(6, 4, zone="quiet", outlet_every=2) + [("O1", "open", False, SeatState.OCCUPIED)],
            "cafe": seats(1, 9, zone="indoor") + [("T1", "terrace", False, SeatState.FREE), ("T2", "terrace", False, SeatState.FREE)],
            "cowork": seats(4, 2, zone="open", outlet_every=1),
        },
        ratios={"qnl": 0.4, "cafe": 0.8, "cowork": 0.3},
    )


def test_recommend_ranks_by_focus_score_and_returns_reasons():
    recs = recommend(city(), Query(arrival_minutes=10))
    assert len(recs) == 3
    scores = [r.focus.score for r in recs]
    assert scores == sorted(scores, reverse=True)
    assert all(r.reasons and r.reasons[0].lower().startswith("about") for r in recs)
    assert any("Simulated" in x for x in recs[0].reasons)


def test_recommend_filters_type_area_zone_outlet_quiet_party():
    data = city()
    assert [r.venue.venue_id for r in recommend(data, Query(venue_type=VenueType.cafe))] == ["cafe"]
    assert [r.venue.venue_id for r in recommend(data, Query(area="Lusail"))] == ["cafe"]
    assert {r.venue.venue_id for r in recommend(data, Query(area="Msheireb"))} == {"cowork"}
    assert [r.venue.venue_id for r in recommend(data, Query(zone="terrace", party_size=2))] == ["cafe"]
    assert "cafe" not in {r.venue.venue_id for r in recommend(data, Query(needs_outlet=True))}
    assert {r.venue.venue_id for r in recommend(data, Query(quiet=True))} == {"qnl"}
    assert recommend(data, Query(party_size=7)) == []


def test_recommend_unknown_area_falls_back_to_all():
    recs = recommend(city(), Query(area="Atlantis"))
    assert len(recs) == 3 and any("not recognised" in x for x in recs[0].reasons)


# --- analytics -------------------------------------------------------------------------

def ev(minutes, seat, old, new):
    return SeatEvent(ts=NOW + timedelta(minutes=minutes), venue_id="v", seat_id=seat, old_state=old, new_state=new)


def test_occupancy_by_hour_and_held_minutes_from_events():
    F, O, H = SeatState.FREE, SeatState.OCCUPIED, SeatState.HELD
    events = [ev(0, "A", F, O), ev(30, "A", O, H), ev(45, "A", H, F), ev(60, "B", F, O)]
    start, end = NOW, NOW + timedelta(hours=2)
    iv = seat_intervals(events, ["A", "B"], start, end)
    by_hour = {r["hour"]: r for r in occupancy_by_hour(iv)}
    # 16:00-17:00: A occupied/held 45 of 60 min, B free -> 37.5 %; held 15 min of 120 seat-min -> 12.5 %
    assert by_hour[16]["occupied_pct"] == pytest.approx(37.5)
    assert by_hour[16]["held_pct"] == pytest.approx(12.5)
    assert by_hour[17]["occupied_pct"] == pytest.approx(50.0)  # B occupied the whole hour
    assert by_hour[3]["occupied_pct"] is None  # not observed
    assert [p["hour"] for p in peak_hours(list(by_hour.values()))] == [17, 16]


def test_state_before_window_is_carried_in():
    events = [ev(-30, "A", SeatState.FREE, SeatState.HELD)]
    iv = seat_intervals(events, ["A"], NOW, NOW + timedelta(minutes=20))
    assert iv["A"] == [(NOW, NOW + timedelta(minutes=20), SeatState.HELD)]


def test_venue_dashboard_respects_observation_start():
    repo = Repository(":memory:")
    repo.add_seat_event(ev(-10, "A", SeatState.FREE, SeatState.OCCUPIED))
    d = venue_dashboard(repo, "v", ["A"], NOW + timedelta(minutes=50), hours=24, observed_since=NOW - timedelta(minutes=10))
    observed = [r for r in d.occupancy_by_hour if r["occupied_pct"] is not None]
    assert {r["hour"] for r in observed} == {15, 16}
    assert all(r["occupied_pct"] == 100.0 for r in observed)
    assert d.held_minutes_total == 0 and not d.includes_synthetic
