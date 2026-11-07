"""Assign detections to seats and turn them into raw observations (CLAUDE.md section 8.1).

Each detection goes to the seat whose polygon contains the box centre; if none does, to the
seat with the largest overlap above MIN_OVERLAP. Other intersecting seats remain uncertain.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

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
        if len(s.seat_polygon) >= 3:
            poly = Polygon(s.seat_polygon)
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
        if det["label"] in _STATE_LABELS and (
            det["label"] == PERSON or not any(seat.workspace_polygon for seat in seats)
        ):
            # An overlapping person or item may obstruct a neighboring seat even when not assigned to it.
            marked = {**det, "label": _UNCERTAIN, "uncertain_label": det["label"]}
            for _, sid in overlaps:
                if sid != target:
                    assigned[sid].append(marked)
        if det["label"] in BELONGINGS:
            for table_id, table in tables.items():
                if not table.is_valid or not table.covers(centre):
                    continue
                linked = [s for s in seats if s.table_id == table_id]
                workspace_hits = []
                for seat in linked:
                    if len(seat.workspace_polygon) < 3:
                        continue
                    workspace = Polygon(seat.workspace_polygon)
                    overlap = workspace.intersection(det_box).area / det_box.area
                    if workspace.covers(centre) or overlap > min_overlap:
                        workspace_hits.append((overlap, seat.seat_id))
                workspace_hits.sort(reverse=True)
                if workspace_hits and (
                    len(workspace_hits) == 1 or workspace_hits[0][0] - workspace_hits[1][0] > _AMBIGUOUS_OVERLAP
                ):
                    workspace_seat = workspace_hits[0][1]
                    if target and target != workspace_seat:
                        assigned[target] = [d for d in assigned[target] if d is not det]
                    if det not in assigned.setdefault(workspace_seat, []):
                        assigned[workspace_seat].append(det)
                    continue
                if len(linked) == 1 and not linked[0].workspace_polygon:
                    assigned.setdefault(linked[0].seat_id, []).append(det)
                    continue
                uncertain = {**det, "label": _UNCERTAIN, "uncertain_label": det["label"]}
                for seat in linked:
                    assigned.setdefault(seat.seat_id, []).append(uncertain)
    return assigned


@dataclass(frozen=True)
class WorkspaceEvidence:
    clear: bool | None
    confidence: float | None
    chair_detected: bool


def workspace_evidence(
    detections: list[dict],
    seats: Iterable[Seat],
    frame_size: tuple[int, int],
    table_regions: dict[str, list[tuple[float, float]]] | None = None,
) -> dict[str, WorkspaceEvidence]:
    """Require a visible calibrated chair and clear desk region before advertising a study space."""
    seats = list(seats)
    seats_by_id = {seat.seat_id: seat for seat in seats}
    seat_regions = seat_polygons(seats)
    workspaces = {
        seat.seat_id: Polygon(seat.workspace_polygon)
        for seat in seats
        if len(seat.workspace_polygon) >= 3
    }
    table_seats = {}
    for seat in seats:
        if seat.table_id:
            table_seats.setdefault(seat.table_id, []).append(seat.seat_id)
    tables = {key: Polygon(points) for key, points in (table_regions or {}).items()}
    w, h = frame_size
    if w <= 0 or h <= 0:
        return {seat.seat_id: WorkspaceEvidence(None, None, False) for seat in seats}

    chair_scores: dict[str, list[float]] = {seat.seat_id: [] for seat in seats}
    blocked: dict[str, list[float]] = {seat.seat_id: [] for seat in seats}
    uncertain: dict[str, list[float]] = {seat.seat_id: [] for seat in seats}
    for det in detections:
        x1, y1, x2, y2 = det["box"]
        box = shapely_box(min(x1 / w, x2 / w), min(y1 / h, y2 / h),
                          max(x1 / w, x2 / w), max(y1 / h, y2 / h))
        if box.area <= 0:
            continue
        centre = box.centroid
        score = float(det["score"])
        if det["label"] == "chair" and score >= DETECTION_THRESHOLD:
            for seat_id, region in seat_regions.items():
                overlap = region.intersection(box).area / box.area
                if region.covers(centre) or overlap > 0.15:
                    chair_scores[seat_id].append(score)
            continue
        if det["label"] not in BELONGINGS | {PERSON}:
            continue
        hits = []
        for seat_id, region in workspaces.items():
            overlap = region.intersection(box).area / box.area
            if region.covers(centre) or overlap > 0.05:
                hits.append((overlap, seat_id))
        hits.sort(reverse=True)
        confident = score >= DETECTION_THRESHOLD
        unique = hits and (len(hits) == 1 or hits[0][0] - hits[1][0] > _AMBIGUOUS_OVERLAP)
        on_tables = [table_id for table_id, region in tables.items() if region.is_valid and region.covers(centre)]
        target_table = seats_by_id[hits[0][1]].table_id if unique else None
        if on_tables and (len(on_tables) != 1 or not unique or target_table != on_tables[0]):
            targets = list(dict.fromkeys(sid for table_id in on_tables for sid in table_seats.get(table_id, [])))
            unique = False
        else:
            targets = [hits[0][1]] if unique else [seat_id for _, seat_id in hits]
        for seat_id in targets:
            (blocked if confident and unique else uncertain)[seat_id].append(score)

    result = {}
    for seat in seats:
        chair = max(chair_scores[seat.seat_id], default=None)
        if seat.seat_id not in seat_regions or seat.seat_id not in workspaces:
            result[seat.seat_id] = WorkspaceEvidence(None, chair, chair is not None)
        elif blocked[seat.seat_id]:
            result[seat.seat_id] = WorkspaceEvidence(False, max(blocked[seat.seat_id]), chair is not None)
        elif uncertain[seat.seat_id]:
            result[seat.seat_id] = WorkspaceEvidence(None, max(uncertain[seat.seat_id]), chair is not None)
        elif chair is not None:
            result[seat.seat_id] = WorkspaceEvidence(True, chair, True)
        else:
            result[seat.seat_id] = WorkspaceEvidence(None, None, False)
    return result


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
