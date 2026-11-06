"""Generate venues/<venue_id>.json for the demo venues.

Simulated venues get example seat regions in normalised 0..1 coordinates, grouped by zone.
The live venue (Nestwork) gets six placeholder seat regions; calibrate them in the venue
configuration before relying on live availability. Its file is only written if it does not
exist yet (pass --force to overwrite).

Run: python scripts/generate_venues.py [--force]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from birdie.models import Seat, Venue, VenueConfig, VenueSource, VenueType  # noqa: E402
from birdie.venues import save_venue, venue_path  # noqa: E402


def grid(
    venue_id: str,
    zone: str,
    prefix: str,
    region: tuple[float, float, float, float],
    rows: int,
    cols: int,
    outlet_every: int = 0,
    start: int = 1,
) -> list[Seat]:
    """Seats laid out in a rows x cols grid inside region (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = region
    cell_w, cell_h = (x1 - x0) / cols, (y1 - y0) / rows
    w, h = cell_w * 0.6, cell_h * 0.6
    seats = []
    n = start
    for r in range(rows):
        for c in range(cols):
            cx, cy = x0 + (c + 0.5) * cell_w, y0 + (r + 0.5) * cell_h
            poly = [
                (round(cx - w / 2, 4), round(cy - h / 2, 4)),
                (round(cx + w / 2, 4), round(cy - h / 2, 4)),
                (round(cx + w / 2, 4), round(cy + h / 2, 4)),
                (round(cx - w / 2, 4), round(cy + h / 2, 4)),
            ]
            has_outlet = outlet_every > 0 and (n - start) % outlet_every == 0
            seats.append(
                Seat(seat_id=f"{prefix}{n:02d}", venue_id=venue_id, zone=zone,
                     has_outlet=has_outlet, polygon=poly)
            )
            n += 1
    return seats


def qnl() -> VenueConfig:
    vid = "qnl"
    seats = (
        grid(vid, "quiet", "Q", (0.03, 0.05, 0.48, 0.95), rows=5, cols=4, outlet_every=1)
        + grid(vid, "open", "O", (0.52, 0.05, 0.97, 0.55), rows=4, cols=4, outlet_every=2)
        + grid(vid, "family", "F", (0.52, 0.60, 0.97, 0.95), rows=2, cols=6)
    )
    venue = Venue(
        venue_id=vid,
        name="Qatar National Library",
        area="Education City",
        type=VenueType.library,
        lat=25.3157,
        lon=51.4394,
        zones=["quiet", "open", "family"],
        source=VenueSource.simulated,
        noise_db=40,
    )
    return VenueConfig(venue=venue, seats=seats)


def qu_library() -> VenueConfig:
    vid = "qu-library"
    seats = (
        grid(vid, "quiet", "Q", (0.03, 0.05, 0.40, 0.95), rows=4, cols=4, outlet_every=1)
        + grid(vid, "women", "W", (0.44, 0.05, 0.97, 0.50), rows=4, cols=5, outlet_every=2)
        + grid(vid, "group", "G", (0.44, 0.56, 0.97, 0.95), rows=2, cols=6, outlet_every=3)
    )
    venue = Venue(
        venue_id=vid,
        name="Qatar University Library",
        area="Qatar University, Al Tarfa",
        type=VenueType.library,
        lat=25.3770,
        lon=51.4890,
        zones=["quiet", "women", "group"],
        source=VenueSource.simulated,
        noise_db=38,
    )
    return VenueConfig(venue=venue, seats=seats)


def qahwa_corner() -> VenueConfig:
    vid = "qahwa-corner"
    seats = (
        grid(vid, "indoor", "I", (0.03, 0.05, 0.60, 0.45), rows=2, cols=6, outlet_every=3)
        + grid(vid, "family", "F", (0.03, 0.55, 0.60, 0.95), rows=2, cols=4)
        + grid(vid, "terrace", "T", (0.66, 0.05, 0.97, 0.95), rows=4, cols=2)
    )
    venue = Venue(
        venue_id=vid,
        name="Qahwa Corner (demo cafe)",
        area="Lusail",
        type=VenueType.cafe,
        lat=25.4196,
        lon=51.4927,
        zones=["indoor", "family", "terrace"],
        source=VenueSource.simulated,
        noise_db=62,
    )
    return VenueConfig(venue=venue, seats=seats)


def nestwork() -> VenueConfig:
    vid = "nestwork-msheireb"
    # Placeholder seats for a webcam looking at two rows of tables. Redraw in the Camera tab.
    seats = grid(vid, "open", "S", (0.02, 0.30, 0.98, 0.98), rows=2, cols=3, outlet_every=2)
    seats = [
        s.model_copy(
            update={
                "polygon": [
                    (round(x0, 4), round(y0, 4))
                    for x0, y0 in _expand(s.polygon, 1.5)
                ]
            }
        )
        for s in seats
    ]
    venue = Venue(
        venue_id=vid,
        name="Nestwork Msheireb",
        area="Msheireb, Doha",
        type=VenueType.cowork,
        lat=25.2867,
        lon=51.5265,
        zones=["open"],
        source=VenueSource.live,
        noise_db=52,
    )
    return VenueConfig(venue=venue, seats=seats)


def _expand(poly: list[tuple[float, float]], factor: float) -> list[tuple[float, float]]:
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    return [
        (min(1.0, max(0.0, cx + (x - cx) * factor)), min(1.0, max(0.0, cy + (y - cy) * factor)))
        for x, y in poly
    ]


def main() -> None:
    force = "--force" in sys.argv
    for cfg in (qnl(), qu_library(), qahwa_corner()):
        print("wrote", save_venue(cfg), len(cfg.seats), "seats")
    live = nestwork()
    if force or not venue_path(live.venue.venue_id).exists():
        print("wrote", save_venue(live), len(live.seats), "seats")
    else:
        print("kept existing", venue_path(live.venue.venue_id))


if __name__ == "__main__":
    main()
