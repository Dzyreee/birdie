"""Decisions for drivers: availability at arrival, focus score, recommendations (CLAUDE.md 8.4, 8.5).

Functions take a `LiveData` object (the BirdieService implements it) so they can be tested with
any fake. Everything returns plain dataclasses with the numbers behind the answer, so the UI can
explain them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from birdie.models import Query, Seat, SeatSnapshot, SeatState, Venue, VenueSource

LIVE_HALF_LIFE_MINUTES = 20.0  # live data counts half as much as the forecast at a 20-minute arrival


class LiveData(Protocol):
    def now(self) -> datetime: ...
    def venues(self) -> list[Venue]: ...
    def venue(self, venue_id: str) -> Venue: ...
    def seats(self, venue_id: str) -> list[Seat]: ...
    def snapshots(self, venue_id: str) -> list[SeatSnapshot]: ...
    def forecast_ratio(self, venue_id: str, ts: datetime) -> float: ...


@dataclass
class Availability:
    venue_id: str
    arrival_minutes: int
    expected_free: float
    low: int
    high: int
    live_free: int
    forecast_free: float
    total: int
    live_weight: float

    @property
    def expected_int(self) -> int:
        return int(round(self.expected_free))

    def summary(self) -> str:
        n = self.expected_int
        seats = "seat" if n == 1 else "seats"
        when = "now" if self.arrival_minutes <= 0 else f"when you arrive in {self.arrival_minutes} min"
        return f"about {n} {seats} likely free {when} (range {self.low} to {self.high})"


def blend_availability(
    *,
    venue_id: str,
    total: int,
    live_free: int,
    forecast_free_now: float,
    forecast_free_arrival: float,
    arrival_minutes: int,
) -> Availability:
    """Pure blending: live data dominates for short arrival times, the forecast for long ones.

    The live count is carried forward along the forecast trend (live_free + forecast change), then
    mixed with the plain forecast with weight w = 0.5 ** (arrival / 20 min). The range widens
    with the arrival time.
    """
    arrival_minutes = max(0, int(arrival_minutes))
    w = 0.5 ** (arrival_minutes / LIVE_HALF_LIFE_MINUTES)
    projected_live = live_free + (forecast_free_arrival - forecast_free_now)
    expected = w * projected_live + (1 - w) * forecast_free_arrival
    expected = float(min(total, max(0.0, expected)))
    spread = 0.5 + total * (0.03 + 0.12 * (1 - w))
    low = max(0, math.floor(expected - spread))
    high = min(total, math.ceil(expected + spread))
    return Availability(
        venue_id=venue_id,
        arrival_minutes=arrival_minutes,
        expected_free=round(expected, 2),
        low=low,
        high=high,
        live_free=live_free,
        forecast_free=round(forecast_free_arrival, 2),
        total=total,
        live_weight=round(w, 3),
    )


def availability_at(data: LiveData, venue_id: str, arrival_minutes: int) -> Availability:
    """Expected free seats at `venue_id` when you arrive in `arrival_minutes`, with a low/high range."""
    now = data.now()
    arrival = now + timedelta(minutes=max(0, arrival_minutes))
    snaps = data.snapshots(venue_id)
    total = len(snaps)
    free_ids = {s.seat_id for s in snaps if s.state == SeatState.FREE}
    return blend_availability(
        venue_id=venue_id,
        total=total,
        live_free=len(free_ids),
        forecast_free_now=total * (1 - data.forecast_ratio(venue_id, now)),
        forecast_free_arrival=total * (1 - data.forecast_ratio(venue_id, arrival)),
        arrival_minutes=arrival_minutes,
    )



# --- focus score ------------------------------------------------------------------------

WEIGHTS = {"free": 40, "noise": 25, "outlets": 20, "trend": 15}
QUIET_DB, LOUD_DB = 35.0, 70.0  # noise_db at or below QUIET_DB scores full points, at LOUD_DB zero
FREE_RATIO_FULL = 0.5  # half the seats free at arrival already scores full points
OUTLETS_FULL = 4  # four free seats with outlets scores full points
TREND_FULL = 0.2  # forecast occupancy falling by 20 points over the next 30 min scores full points
QUIET_NOISE_DB = 50.0  # venues at or below this count as quiet


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class ScorePart:
    key: str
    label: str
    weight: int
    points: float
    value: str


@dataclass
class FocusScore:
    venue_id: str
    score: int
    parts: list[ScorePart]
    availability: Availability
    free_outlets: int
    trend: float  # forecast occupancy change over the 30 min after arrival (negative = emptying)

    @property
    def trend_label(self) -> str:
        if self.trend <= -0.05:
            return "emptying"
        if self.trend >= 0.05:
            return "filling up"
        return "steady"


def _free_now(data: LiveData, venue_id: str) -> list[SeatSnapshot]:
    return [s for s in data.snapshots(venue_id) if s.state == SeatState.FREE]


def focus_score(data: LiveData, venue_id: str, arrival_minutes: int) -> FocusScore:
    """0 to 100: free-seat ratio at arrival (40), noise (25), free seats with outlets (20), crowd trend (15)."""
    venue = data.venue(venue_id)
    avail = availability_at(data, venue_id, arrival_minutes)
    now = data.now()
    arrival = now + timedelta(minutes=max(0, arrival_minutes))

    free_ratio = avail.expected_free / avail.total if avail.total else 0.0
    p_free = WEIGHTS["free"] * _clamp(free_ratio / FREE_RATIO_FULL)

    p_noise = WEIGHTS["noise"] * _clamp((LOUD_DB - venue.noise_db) / (LOUD_DB - QUIET_DB))

    free_now = _free_now(data, venue_id)
    live_outlets = sum(1 for s in free_now if s.has_outlet)
    # Scale today's free outlet seats by how the free-seat count is expected to move by arrival.
    scale = avail.expected_free / avail.live_free if avail.live_free else (1.0 if avail.expected_free else 0.0)
    outlets_at_arrival = live_outlets * min(1.5, scale)
    p_outlets = WEIGHTS["outlets"] * _clamp(outlets_at_arrival / OUTLETS_FULL)

    trend = data.forecast_ratio(venue_id, arrival + timedelta(minutes=30)) - data.forecast_ratio(venue_id, arrival)
    p_trend = WEIGHTS["trend"] * _clamp(0.5 - trend / (2 * TREND_FULL))

    parts = [
        ScorePart("free", "Free seats at arrival", WEIGHTS["free"], round(p_free, 1),
                  f"≈{avail.expected_int} of {avail.total} ({free_ratio:.0%})"),
        ScorePart("noise", "Noise level", WEIGHTS["noise"], round(p_noise, 1), f"{venue.noise_db:.0f} dB"),
        ScorePart("outlets", "Free seats with outlets", WEIGHTS["outlets"], round(p_outlets, 1),
                  f"≈{round(outlets_at_arrival)}"),
        ScorePart("trend", "Crowd trend", WEIGHTS["trend"], round(p_trend, 1),
                  "emptying" if trend <= -0.05 else "filling up" if trend >= 0.05 else "steady"),
    ]
    score = int(round(_clamp(sum(p.points for p in parts), 0, 100)))
    return FocusScore(venue_id, score, parts, avail, int(round(outlets_at_arrival)), round(trend, 3))


# --- recommendations ------------------------------------------------------------------------

# Rough centres of Doha areas, so "near West Bay" works even with no venue in West Bay.
AREA_COORDS: dict[str, tuple[float, float]] = {
    "msheireb": (25.2867, 51.5265),
    "downtown": (25.2867, 51.5265),
    "souq waqif": (25.2877, 51.5330),
    "west bay": (25.3225, 51.5310),
    "corniche": (25.3050, 51.5300),
    "lusail": (25.4196, 51.4927),
    "the pearl": (25.3700, 51.5510),
    "pearl": (25.3700, 51.5510),
    "katara": (25.3600, 51.5260),
    "education city": (25.3157, 51.4394),
    "al rayyan": (25.2919, 51.4244),
    "qatar university": (25.3770, 51.4890),
    "al tarfa": (25.3770, 51.4890),
    "al sadd": (25.2846, 51.4950),
    "al wakrah": (25.1715, 51.6034),
    "doha": (25.2854, 51.5310),
}
NEAR_KM = 8.0


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def _area_point(area: str) -> tuple[float, float] | None:
    a = area.strip().lower()
    for name, point in AREA_COORDS.items():
        if name in a or a in name:
            return point
    return None


@dataclass
class Recommendation:
    venue: Venue
    focus: FocusScore
    availability: Availability
    reasons: list[str]
    zone_free: dict[str, int] = field(default_factory=dict)
    distance_km: float | None = None


def zone_free_now(data: LiveData, venue_id: str) -> dict[str, int]:
    """Free seats per zone right now."""
    out = {z: 0 for z in data.venue(venue_id).zones}
    for s in _free_now(data, venue_id):
        out[s.zone] = out.get(s.zone, 0) + 1
    return out


def recommend(data: LiveData, query: Query, top: int = 3) -> list[Recommendation]:
    """Filter venues by the query, rank by focus score at arrival, return the top ones with reasons."""
    from birdie.venues import zone_label

    venues = data.venues()
    if query.venue_type:
        venues = [v for v in venues if v.type == query.venue_type]

    distances: dict[str, float] = {}
    area_note = None
    if query.area:
        a = query.area.strip().lower()
        point = _area_point(a)
        if point:
            distances = {v.venue_id: _distance_km(point, (v.lat, v.lon)) for v in venues}
        matched = [
            v for v in venues
            if a in v.area.lower() or a in v.name.lower() or distances.get(v.venue_id, 1e9) <= NEAR_KM
        ]
        if matched:
            venues = matched
        else:
            area_note = f"Nothing within {NEAR_KM:.0f} km of {query.area}" if point else f"Area '{query.area}' not recognised"

    out: list[Recommendation] = []
    for v in venues:
        focus = focus_score(data, v.venue_id, query.arrival_minutes)
        avail = focus.availability
        zones = zone_free_now(data, v.venue_id)
        if avail.expected_int < query.party_size:
            continue
        if query.zone and zones.get(query.zone, 0) < query.party_size:
            continue
        free_outlets_now = sum(1 for s in _free_now(data, v.venue_id) if s.has_outlet)
        if query.needs_outlet and free_outlets_now < 1:
            continue
        quiet_zone_free = zones.get("quiet", 0)
        if query.quiet and not (v.noise_db <= QUIET_NOISE_DB or quiet_zone_free >= query.party_size):
            continue

        reasons = [avail.summary().capitalize()]
        reasons.append(f"Focus score {focus.score}/100")
        if query.zone:
            reasons.append(f"{zone_label(query.zone)}: {zones.get(query.zone, 0)} free now")
        if query.quiet or v.noise_db <= QUIET_NOISE_DB:
            reasons.append(f"Quiet: {v.noise_db:.0f} dB" + (f", quiet zone has {quiet_zone_free} free" if "quiet" in zones else ""))
        if free_outlets_now:
            reasons.append(f"{free_outlets_now} free seats with outlets now")
        if focus.trend_label != "steady":
            reasons.append(f"Crowd {focus.trend_label} after you arrive")
        if v.venue_id in distances:
            reasons.append(f"{distances[v.venue_id]:.1f} km from {query.area}")
        if area_note:
            reasons.append(area_note)
        if v.source == VenueSource.simulated:
            reasons.append("Simulated venue (demo data)")
        out.append(Recommendation(v, focus, avail, reasons, zones, distances.get(v.venue_id)))

    out.sort(key=lambda r: (-r.focus.score, r.distance_km or 0.0))
    return out[:top]
