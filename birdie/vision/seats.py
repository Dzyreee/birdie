"""Assign detections to seats and turn them into raw observations (CLAUDE.md section 8.1).

Each detection goes to the seat whose polygon contains the box centre; if none does, to the
seat with the largest overlap above MIN_OVERLAP. Other intersecting seats remain uncertain.
"""

from __future__ import annotations

from collections.abc import Iterable

from shapely.geometry import Point, Polygon
from shapely.geometry import box as shapely_box

from birdie.config import DETECTION_THRESHOLD, MIN_OVERLAP
from birdie.models import Seat
from birdie.vision.detector import BELONGINGS, PERSON
from birdie.vision.state import Observation, SeatEvidence

_UNCERTAIN = "_uncertain"
_AMBIGUOUS_OVERLAP = 0.05
_STATE_LABELS = BELONGINGS | {PERSON}


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
    table_regions: dict[str, list[tuple[float, float]]] | None = None,
) -> dict[str, list[dict]]:
    """Map seat_id -> detections on that seat. frame_size is (width, height) in pixels."""
    seats = list(seats)
    polys = seat_polygons(seats)
    tables = {key: Polygon(points) for key, points in (table_regions or {}).items()}
    assigned: dict[str, list[dict]] = {sid: [] for sid in polys}
    w, h = frame_size
    if w <= 0 or h <= 0:
        return assigned
    for det in detections:
        x1, y1, x2, y2 = det["box"]
        nx1, ny1, nx2, ny2 = x1 / w, y1 / h, x2 / w, y2 / h
        det_box = shapely_box(min(nx1, nx2), min(ny1, ny2), max(nx1, nx2), max(ny1, ny2))
        if det_box.area <= 0:
            continue
        overlaps = []
        for sid, p in polys.items():
            overlap = p.intersection(det_box).area / det_box.area
            if overlap > 0:
                overlaps.append((overlap, sid))
        overlaps.sort(reverse=True)
        centre = Point((nx1 + nx2) / 2, (ny1 + ny2) / 2)
        containing = [sid for sid, p in polys.items() if p.contains(centre)]
        target = None
        if containing:
            if len(containing) == 1:
                target = containing[0]
        else:
            eligible = [(overlap, sid) for overlap, sid in overlaps if overlap > min_overlap]
            if eligible and (len(eligible) == 1 or eligible[0][0] - eligible[1][0] > _AMBIGUOUS_OVERLAP):
                target = eligible[0][1]
        if target is not None:
            assigned[target].append(det)
        if det["label"] in _STATE_LABELS:
            # An overlapping person or item may obstruct a neighboring seat even when not assigned to it.
            marked = {**det, "label": _UNCERTAIN, "uncertain_label": det["label"]}
            for _, sid in overlaps:
                if sid != target:
                    assigned[sid].append(marked)
        if det["label"] in BELONGINGS:
            for table_id, table in tables.items():
                if not table.is_valid or not table.covers(centre):
                    continue
                linked = [s.seat_id for s in seats if s.table_id == table_id]
                for sid in linked:
                    evidence = assigned.setdefault(sid, [])
                    if sid == target:
                        continue
                    if len(linked) == 1:
                        evidence.append(det)
                    else:
                        evidence.append({**det, "label": _UNCERTAIN, "uncertain_label": det["label"]})
    return assigned


def observe(assigned: dict[str, list[dict]]) -> dict[str, Observation]:
    """PERSON if any person is on the seat, else ITEMS if any belongings, else EMPTY."""
    out = {}
    for seat_id, dets in assigned.items():
        labels = {d["label"] for d in dets}
        if PERSON in labels:
            out[seat_id] = Observation.PERSON
        elif _UNCERTAIN in labels:
            out[seat_id] = Observation.UNKNOWN
        elif labels & BELONGINGS:
            out[seat_id] = Observation.ITEMS
        else:
            out[seat_id] = Observation.EMPTY
    return out


def observe_evidence(assigned: dict[str, list[dict]]) -> dict[str, SeatEvidence]:
    """Keep per-seat confidence and mark weak or ambiguous evidence UNKNOWN."""
    out = {}
    for seat_id, dets in assigned.items():
        people = [d for d in dets if d["label"] == PERSON and d["score"] >= DETECTION_THRESHOLD]
        items = [d for d in dets if d["label"] in BELONGINGS and d["score"] >= DETECTION_THRESHOLD]
        weak = [d for d in dets if d["label"] in _STATE_LABELS and d["score"] < DETECTION_THRESHOLD]
        ambiguous = [d for d in dets if d["label"] == _UNCERTAIN and d.get("uncertain_label") in _STATE_LABELS]
        uncertain_person = any(d["label"] == PERSON for d in weak) or any(
            d.get("uncertain_label") == PERSON for d in ambiguous
        )
        if people:
            out[seat_id] = SeatEvidence(
                Observation.PERSON, True, bool(items), max(d["score"] for d in people)
            )
        elif uncertain_person or ((weak or ambiguous) and not items):
            scores = [
                d["score"] for d in dets
                if d["label"] in _STATE_LABELS
                or (d["label"] == _UNCERTAIN and d.get("uncertain_label") in _STATE_LABELS)
            ]
            out[seat_id] = SeatEvidence(
                Observation.UNKNOWN, None, None, max(scores) if scores else None
            )
        elif items:
            out[seat_id] = SeatEvidence(
                Observation.ITEMS, False, True, max(d["score"] for d in items)
            )
        else:
            out[seat_id] = SeatEvidence(Observation.EMPTY, False, False, None)
    return out
