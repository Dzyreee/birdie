"""Assign detections to seats and turn them into raw observations (CLAUDE.md section 8.1).

Each detection goes to the seat whose polygon contains the box centre; if none does, to the
seat with the largest overlap above MIN_OVERLAP (fraction of the box area inside the polygon).
"""

from __future__ import annotations

from collections.abc import Iterable

from shapely.geometry import Point, Polygon
from shapely.geometry import box as shapely_box

from birdie.config import MIN_OVERLAP
from birdie.models import Seat
from birdie.vision.detector import BELONGINGS, PERSON
from birdie.vision.state import Observation


def seat_polygons(seats: Iterable[Seat]) -> dict[str, Polygon]:
    polys = {}
    for s in seats:
        if len(s.polygon) >= 3:
            poly = Polygon(s.polygon)
            if not poly.is_valid:
                poly = poly.buffer(0)  # fix self-intersecting corner orders
            if poly.area > 0:
                polys[s.seat_id] = poly
    return polys


def assign_detections(
    detections: list[dict],
    seats: Iterable[Seat],
    frame_size: tuple[int, int],
    min_overlap: float = MIN_OVERLAP,
) -> dict[str, list[dict]]:
    """Map seat_id -> detections on that seat. frame_size is (width, height) in pixels."""
    polys = seat_polygons(seats)
    assigned: dict[str, list[dict]] = {sid: [] for sid in polys}
    w, h = frame_size
    if w <= 0 or h <= 0:
        return assigned
    for det in detections:
        x1, y1, x2, y2 = det["box"]
        nx1, ny1, nx2, ny2 = x1 / w, y1 / h, x2 / w, y2 / h
        centre = Point((nx1 + nx2) / 2, (ny1 + ny2) / 2)
        containing = [sid for sid, p in polys.items() if p.contains(centre)]
        if containing:
            # Several polygons can contain the centre if they overlap: take the tightest.
            seat_id = min(containing, key=lambda sid: polys[sid].area)
            assigned[seat_id].append(det)
            continue
        det_box = shapely_box(min(nx1, nx2), min(ny1, ny2), max(nx1, nx2), max(ny1, ny2))
        if det_box.area <= 0:
            continue
        best_id, best_overlap = None, min_overlap
        for sid, p in polys.items():
            overlap = p.intersection(det_box).area / det_box.area
            if overlap > best_overlap:
                best_id, best_overlap = sid, overlap
        if best_id is not None:
            assigned[best_id].append(det)
    return assigned


def observe(assigned: dict[str, list[dict]]) -> dict[str, Observation]:
    """PERSON if any person is on the seat, else ITEMS if any belongings, else EMPTY."""
    out = {}
    for seat_id, dets in assigned.items():
        labels = {d["label"] for d in dets}
        if PERSON in labels:
            out[seat_id] = Observation.PERSON
        elif labels & BELONGINGS:
            out[seat_id] = Observation.ITEMS
        else:
            out[seat_id] = Observation.EMPTY
    return out
