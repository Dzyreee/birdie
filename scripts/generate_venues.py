"""Generate venues/<venue_id>.json for the 7 Doha venues (CLAUDE.md section 7.3, web/mock.js).

Floor plans and chair positions follow the design handoff: LAYOUTS and chairsFor() in
design/mobile/prototype.html, ported to Python below. Seat ids are the table letter plus a number
(A3), or just the letter for single focus pods. Nestwork gets a small placeholder plan until it is
redrawn from a sketch of the real room; its camera polygons come from "Detect chairs" in the operator
console, so its file is only rewritten with --force (to keep any saved polygons).

Run: python scripts/generate_venues.py [--force]
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from birdie.models import (  # noqa: E402
    Fixture,
    FloorPlan,
    Seat,
    Table,
    Venue,
    VenueConfig,
    VenueSource,
)
from birdie.venues import save_venue, venue_path  # noqa: E402

OFF = 17  # distance from a table edge to the centre of its chairs, in plan points

# design/mobile/prototype.html LAYOUTS. Chair counts per side: t, b, l, r; n around a round table.
LAYOUTS = {
    "library": {"h": 490, "window_top": True, "tables": [
        {"k": "W", "name": "Window bar", "x": 24, "y": 22, "w": 314, "h": 16, "b": 8, "window": True, "outlet": True},
        {"k": "A", "name": "Table A", "x": 34, "y": 118, "w": 130, "h": 46, "t": 3, "b": 3, "outlet": True},
        {"k": "B", "name": "Table B", "x": 198, "y": 118, "w": 130, "h": 46, "t": 3, "b": 3},
        {"k": "C", "name": "Round table C", "cx": 96, "cy": 272, "r": 30, "n": 4},
        {"k": "D", "name": "Round table D", "cx": 266, "cy": 272, "r": 30, "n": 4, "outlet": True},
        {"k": "E", "name": "Booth E", "x": 60, "y": 366, "w": 56, "h": 72, "l": 2, "r": 2, "outlet": True},
        {"k": "F", "name": "Booth F", "x": 246, "y": 366, "w": 56, "h": 72, "l": 2, "r": 2, "outlet": True},
    ], "fixtures": [{"label": "Books", "x": 152, "y": 370, "w": 58, "h": 64}]},
    "cafe": {"h": 430, "window_top": True, "tables": [
        {"k": "W", "name": "Window bar", "x": 24, "y": 22, "w": 314, "h": 16, "b": 6, "window": True},
        {"k": "R", "name": "Café table R", "cx": 72, "cy": 150, "r": 22, "n": 3, "outlet": True},
        {"k": "S", "name": "Café table S", "cx": 181, "cy": 150, "r": 22, "n": 3},
        {"k": "T", "name": "Café table T", "cx": 290, "cy": 150, "r": 22, "n": 3},
        {"k": "L", "name": "Long table", "x": 60, "y": 240, "w": 242, "h": 44, "t": 5, "b": 5, "outlet": True},
    ], "fixtures": [{"label": "Counter", "x": 210, "y": 340, "w": 128, "h": 40}]},
    "cowork": {"h": 430, "window_top": True, "tables": [
        {"k": "D", "name": "Desk row D", "x": 40, "y": 44, "w": 282, "h": 40, "t": 5, "b": 5, "outlet": True,
         "window": True},
        {"k": "E", "name": "Desk row E", "x": 40, "y": 172, "w": 282, "h": 40, "t": 5, "b": 5, "outlet": True},
        {"k": "P", "name": "Focus pod", "x": 24, "y": 290, "w": 60, "h": 34, "b": 1, "outlet": True, "single": True},
        {"k": "Q", "name": "Focus pod", "x": 108, "y": 290, "w": 60, "h": 34, "b": 1, "outlet": True, "single": True},
        {"k": "R", "name": "Focus pod", "x": 194, "y": 290, "w": 60, "h": 34, "b": 1, "outlet": True, "single": True},
        {"k": "S", "name": "Focus pod", "x": 278, "y": 290, "w": 60, "h": 34, "b": 1, "outlet": True, "single": True},
    ], "fixtures": []},
    "study": {"h": 360, "window_top": False, "tables": [
        {"k": "G", "name": "Table G", "x": 40, "y": 50, "w": 120, "h": 56, "t": 3, "b": 3, "outlet": True},
        {"k": "H", "name": "Table H", "x": 202, "y": 50, "w": 120, "h": 56, "t": 3, "b": 3},
        {"k": "I", "name": "Round table I", "cx": 181, "cy": 240, "r": 34, "n": 6},
    ], "fixtures": []},
    # PLACEHOLDER for Nestwork Msheireb: two tables of four in front of the camera. Replace from a sketch of
    # the real demo room (table letters, chairs per side), then redo "Detect chairs" in the operator console.
    "nestwork": {"h": 360, "window_top": False, "tables": [
        {"k": "A", "name": "Table A", "x": 46, "y": 110, "w": 120, "h": 60, "t": 2, "b": 2, "outlet": True},
        {"k": "B", "name": "Table B", "x": 196, "y": 110, "w": 120, "h": 60, "t": 2, "b": 2},
    ], "fixtures": [{"label": "Camera", "x": 151, "y": 300, "w": 60, "h": 30}]},
}

# The 7 venues of web/mock.js; names, areas and drive times from CLAUDE.md section 7.3 where listed.
# zone_of maps table letters to zones (amenity chips show the zones).
VENUES = [
    {"venue_id": "nestwork-msheireb", "name": "Nestwork Msheireb", "area": "Msheireb Downtown", "type": "cowork",
     "lat": 25.2867, "lon": 51.5265, "source": "live", "drive_minutes": 0, "open_until": "Open till 22:00",
     "open_late": True, "amenities": ["Wi-Fi", "Outlets", "Coffee"], "zones": ["open"], "layout": "nestwork",
     "noise_db": 52, "zone_of": {}},
    {"venue_id": "qnl", "name": "Qatar National Library", "area": "Education City", "type": "library",
     "lat": 25.3147, "lon": 51.4405, "source": "simulated", "drive_minutes": 15, "open_until": "Open till 22:00",
     "open_late": True, "amenities": ["Quiet zone", "Women's section", "Wi-Fi", "Outlets"],
     "zones": ["quiet", "open", "women"], "layout": "library", "noise_db": 40,
     "zone_of": {"W": "quiet", "A": "quiet", "B": "open", "C": "open", "D": "open", "E": "women", "F": "women"}},
    {"venue_id": "qu-library", "name": "Qatar University Library", "area": "Qatar University", "type": "library",
     "lat": 25.377, "lon": 51.49, "source": "simulated", "drive_minutes": 25, "open_until": "Open till 21:00",
     "open_late": False, "amenities": ["Quiet zone", "Women's section", "Printing"], "zones": ["quiet", "women"],
     "layout": "library", "noise_db": 38,
     "zone_of": {"W": "quiet", "A": "quiet", "B": "quiet", "C": "women", "D": "women", "E": "women", "F": "women"}},
    {"venue_id": "qahwa-corner", "name": "Qahwa Corner", "area": "Lusail", "type": "cafe",
     "lat": 25.42, "lon": 51.49, "source": "simulated", "drive_minutes": 25, "open_until": "Open till 01:00",
     "open_late": True, "amenities": ["Wi-Fi", "Family section", "Food"], "zones": ["family", "terrace"],
     "layout": "cafe", "noise_db": 62,
     "zone_of": {"W": "family", "R": "terrace", "S": "terrace", "T": "terrace", "L": "family"}},
    {"venue_id": "corniche-cup", "name": "Corniche Cup", "area": "West Bay", "type": "cafe",  # invented
     "lat": 25.322, "lon": 51.53, "source": "simulated", "drive_minutes": 10, "open_until": "Open till 23:00",
     "open_late": True, "amenities": ["Wi-Fi", "Outlets", "Terrace"], "zones": ["open", "terrace"],
     "layout": "cafe", "noise_db": 60,
     "zone_of": {"W": "open", "R": "terrace", "S": "terrace", "T": "terrace", "L": "open"}},
    {"venue_id": "nakheel-study", "name": "Nakheel Study Rooms", "area": "Al Sadd", "type": "study_room",  # invented
     "lat": 25.285, "lon": 51.5, "source": "simulated", "drive_minutes": 12, "open_until": "Open till 00:00",
     "open_late": True, "amenities": ["Quiet zone", "Outlets"], "zones": ["quiet"], "layout": "study",
     "noise_db": 36, "zone_of": {}},
    {"venue_id": "waab-study-hall", "name": "Al Waab Study Hall", "area": "Al Waab", "type": "study_room",  # invented
     "lat": 25.263, "lon": 51.45, "source": "simulated", "drive_minutes": 20, "open_until": "Open till 22:00",
     "open_late": False, "amenities": ["Quiet zone", "Women's section"], "zones": ["quiet", "women"],
     "layout": "study", "noise_db": 36, "zone_of": {"G": "quiet", "H": "quiet", "I": "women"}},
]


def _r1(v: float) -> float:
    """Round like the app's Math.round(n * 10) / 10."""
    return math.floor(v * 10 + 0.5) / 10


def chairs_for(layout: dict, venue_id: str, zone_of: dict, default_zone: str) -> list[Seat]:
    """Port of chairsFor(): chairs on each side of rect tables, radially around round ones."""
    seats: list[Seat] = []
    for t in layout["tables"]:
        count = 0

        def add(x: float, y: float, rot: float, t=t) -> None:
            nonlocal count
            count += 1
            seats.append(Seat(
                seat_id=t["k"] if t.get("single") else f"{t['k']}{count}", venue_id=venue_id, table_id=t["k"],
                zone=zone_of.get(t["k"], default_zone), has_outlet=bool(t.get("outlet")),
                has_window=bool(t.get("window")), plan_x=_r1(x), plan_y=_r1(y), plan_rot=_r1(rot),
            ))

        if "n" in t:
            for i in range(t["n"]):
                a = -math.pi / 2 + 2 * math.pi * i / t["n"]
                add(t["cx"] + (t["r"] + OFF) * math.cos(a), t["cy"] + (t["r"] + OFF) * math.sin(a),
                    a * 180 / math.pi + 90)
        else:
            for i in range(t.get("t", 0)):
                add(t["x"] + t["w"] * (i + 0.5) / t["t"], t["y"] - OFF, 0)
            for i in range(t.get("b", 0)):
                add(t["x"] + t["w"] * (i + 0.5) / t["b"], t["y"] + t["h"] + OFF, 180)
            for i in range(t.get("l", 0)):
                add(t["x"] - OFF, t["y"] + t["h"] * (i + 0.5) / t["l"], -90)
            for i in range(t.get("r", 0)):
                add(t["x"] + t["w"] + OFF, t["y"] + t["h"] * (i + 0.5) / t["r"], 90)
    return seats


def floor_plan(layout: dict) -> FloorPlan:
    tables = []
    for t in layout["tables"]:
        if "n" in t:
            tables.append(Table(table_id=t["k"], name=t["name"], shape="round", cx=t["cx"], cy=t["cy"], r=t["r"]))
        else:
            tables.append(Table(table_id=t["k"], name=t["name"], shape="rect", x=t["x"], y=t["y"], w=t["w"], h=t["h"]))
    return FloorPlan(width=362, height=layout["h"], window_top=layout["window_top"], tables=tables,
                     fixtures=[Fixture(**f) for f in layout["fixtures"]])


def build(spec: dict) -> VenueConfig:
    layout = LAYOUTS[spec["layout"]]
    fields = {k: v for k, v in spec.items() if k not in ("layout", "zone_of")}
    venue = Venue.model_validate(fields | {"floor_plan": floor_plan(layout)})
    seats = chairs_for(layout, spec["venue_id"], spec["zone_of"], spec["zones"][0])
    return VenueConfig(venue=venue, seats=seats)


def main() -> None:
    force = "--force" in sys.argv
    for spec in VENUES:
        cfg = build(spec)
        path = venue_path(cfg.venue.venue_id)
        if cfg.venue.source == VenueSource.live and path.exists() and not force:
            print("kept existing", path, "(use --force to replace it and lose its camera polygons)")
            continue
        print("wrote", save_venue(cfg), len(cfg.seats), "seats")


if __name__ == "__main__":
    main()
