"""One seat per chair: turn detected chairs into seat outlines for the seat setup tool.

The operator takes a snapshot from the clip, runs the detector, and every detected chair becomes a
candidate outline (its box, expanded a little). Candidates are numbered left to right so they can be
matched to the floor plan's seat ids. Only the camera polygon is saved into the existing seat.
"""

from __future__ import annotations

import re

from birdie.vision.detector import CHAIR

CHAIR_MIN_SCORE = 0.3  # chairs are often half hidden by people and tables, so accept lower scores
CHAIR_PAD = 0.1  # expand each chair box by 10% of its size on every side
DUPLICATE_IOU = 0.6  # two chair boxes overlapping this much are the same chair


def _iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def chair_candidates(
    detections: list[dict],
    frame_size: tuple[int, int],
    min_score: float = CHAIR_MIN_SCORE,
    pad: float = CHAIR_PAD,
) -> list[dict]:
    """Detected chairs as seat outlines, sorted left to right (then top to bottom).

    Returns [{"box": [x1, y1, x2, y2] normalised, "polygon": [(x, y) x4] normalised, "score": float}].
    """
    w, h = frame_size
    boxes = sorted(
        (d for d in detections if d["label"] == CHAIR and d["score"] >= min_score),
        key=lambda d: -d["score"],
    )
    kept: list[dict] = []
    for d in boxes:
        x1, y1, x2, y2 = d["box"]
        nb = [x1 / w, y1 / h, x2 / w, y2 / h]
        if any(_iou(nb, k["box"]) >= DUPLICATE_IOU for k in kept):
            continue
        bw, bh = nb[2] - nb[0], nb[3] - nb[1]
        px1, py1 = max(0.0, nb[0] - bw * pad), max(0.0, nb[1] - bh * pad)
        px2, py2 = min(1.0, nb[2] + bw * pad), min(1.0, nb[3] + bh * pad)
        polygon = [(round(px1, 4), round(py1, 4)), (round(px2, 4), round(py1, 4)),
                   (round(px2, 4), round(py2, 4)), (round(px1, 4), round(py2, 4))]
        kept.append({"box": [round(v, 4) for v in nb], "polygon": polygon, "score": round(float(d["score"]), 3)})
    return sorted(kept, key=lambda c: ((c["box"][0] + c["box"][2]) / 2, (c["box"][1] + c["box"][3]) / 2))


def natural_key(seat_id: str) -> tuple:
    """Sort A2 before A10, and table letters alphabetically."""
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", seat_id))


def auto_number(candidates: list[dict], seat_ids: list[str]) -> list[str | None]:
    """Give the candidates (already left to right) the venue's seat ids in floor-plan order.

    Returns one seat id per candidate (None when there are more chairs than seats).
    """
    ordered = sorted(seat_ids, key=natural_key)
    return [ordered[i] if i < len(ordered) else None for i in range(len(candidates))]
