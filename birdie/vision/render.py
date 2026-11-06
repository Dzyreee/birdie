"""Draw annotated frames for the operator console. People are always blurred.

Order: blur people first, then seat outlines in the seat colours, then detector boxes on top.
Frames are encoded to in-memory JPEG data URLs for the browser. Nothing is written to disk.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable

import cv2
import numpy as np

from birdie.models import Seat, SeatSnapshot, SeatState
from birdie.vision.detector import CHAIR, PERSON

# RGB, from CLAUDE.md section 5 (seat colours): Free green, Taken charcoal, Held amber.
STATE_COLORS = {
    SeatState.FREE: (23, 128, 79),  # #17804F
    SeatState.OCCUPIED: (53, 58, 66),  # #353A42
    SeatState.HELD: (208, 138, 28),  # #D08A1C
}
STATE_LABELS = {SeatState.FREE: "Free", SeatState.OCCUPIED: "Taken", SeatState.HELD: "Held"}
BOX_PERSON = (148, 163, 184)
BOX_CHAIR = (120, 190, 255)
BOX_ITEM = (56, 189, 248)
SETUP_COLOR = (217, 70, 239)
CANDIDATE_COLOR = (255, 196, 0)
NUMBERED_COLOR = (56, 132, 255)  # neutral blue: no state or detector hint for labellers


def blur_people(frame: np.ndarray, boxes: Iterable[list[float]], pad: float = 0.12) -> np.ndarray:
    """Pixelate then blur every person box (plus padding). Returns a new array."""
    out = frame.copy()
    h, w = out.shape[:2]
    for x1, y1, x2, y2 in boxes:
        bw, bh = x2 - x1, y2 - y1
        x1i = int(max(0, x1 - bw * pad))
        y1i = int(max(0, y1 - bh * pad))
        x2i = int(min(w, x2 + bw * pad))
        y2i = int(min(h, y2 + bh * pad))
        if x2i - x1i < 2 or y2i - y1i < 2:
            continue
        roi = out[y1i:y2i, x1i:x2i]
        small = cv2.resize(roi, (max(1, (x2i - x1i) // 16), max(1, (y2i - y1i) // 16)), interpolation=cv2.INTER_AREA)
        mosaic = cv2.resize(small, (x2i - x1i, y2i - y1i), interpolation=cv2.INTER_NEAREST)
        out[y1i:y2i, x1i:x2i] = cv2.GaussianBlur(mosaic, (0, 0), sigmaX=max(3, (x2i - x1i) / 30))
    return out


def _to_px(poly: list[tuple[float, float]], w: int, h: int) -> np.ndarray:
    return np.array([[int(x * w), int(y * h)] for x, y in poly], dtype=np.int32)


def _label(img: np.ndarray, text: str, org: tuple[int, int], color: tuple[int, int, int], scale: float = 0.45) -> None:
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
    x, y = org
    y = max(th + 4, y)
    cv2.rectangle(img, (x, y - th - 4), (x + tw + 4, y + base - 2), color, -1)
    cv2.putText(img, text, (x + 2, y - 2), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 1, cv2.LINE_AA)


def draw_seats(img: np.ndarray, seats: Iterable[Seat], snapshots: dict[str, SeatSnapshot]) -> np.ndarray:
    """Seat outlines filled lightly and outlined in the seat colour, labelled with id and state."""
    h, w = img.shape[:2]
    seats = [s for s in seats if len(s.polygon) >= 3]
    if not seats:
        return img
    overlay = img.copy()
    for seat in seats:
        snap = snapshots.get(seat.seat_id)
        cv2.fillPoly(overlay, [_to_px(seat.polygon, w, h)], STATE_COLORS[snap.state if snap else SeatState.FREE])
    img = cv2.addWeighted(overlay, 0.22, img, 0.78, 0)
    for seat in seats:
        snap = snapshots.get(seat.seat_id)
        state = snap.state if snap else SeatState.FREE
        pts = _to_px(seat.polygon, w, h)
        cv2.polylines(img, [pts], True, STATE_COLORS[state], 2, cv2.LINE_AA)
        _label(img, f"{seat.seat_id} {STATE_LABELS[state]}", (int(pts[:, 0].min()) + 2, int(pts[:, 1].min()) + 16),
               STATE_COLORS[state])
    return img


def draw_detections(img: np.ndarray, detections: list[dict]) -> np.ndarray:
    """Detector boxes with label and score (drawn on top of the blurred frame)."""
    h = img.shape[0]
    for d in detections:
        x1, y1, x2, y2 = (int(v) for v in d["box"])
        color = BOX_PERSON if d["label"] == PERSON else BOX_CHAIR if d["label"] == CHAIR else BOX_ITEM
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 1, cv2.LINE_AA)
        _label(img, f"{d['label']} {d['score']:.2f}", (x1, y2 + 14 if y2 + 14 < h else y1 + 14), color, 0.38)
    return img


def annotate(
    frame: np.ndarray,
    detections: list[dict],
    seats: Iterable[Seat] = (),
    snapshots: dict[str, SeatSnapshot] | None = None,
    blur_boxes: Iterable[list[float]] | None = None,
    show_boxes: bool = True,
) -> np.ndarray:
    """RGB frame in, annotated RGB frame out: people blurred, seat outlines, detection boxes on top."""
    person_boxes = [d["box"] for d in detections if d["label"] == PERSON]
    img = blur_people(frame, list(person_boxes) + list(blur_boxes or []))
    img = draw_seats(img, seats, snapshots or {})
    if show_boxes:
        img = draw_detections(img, detections)
    return img


def draw_candidates(frame: np.ndarray, candidates: list[dict]) -> np.ndarray:
    """Chair candidates from "Detect chairs": an outline and a big number each."""
    img = frame.copy()
    h, w = img.shape[:2]
    for i, c in enumerate(candidates):
        pts = _to_px(c["polygon"], w, h)
        cv2.polylines(img, [pts], True, CANDIDATE_COLOR, 2, cv2.LINE_4)
        cx, cy = int(pts[:, 0].mean()), int(pts[:, 1].mean())
        text = str(i + 1)
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
        cv2.circle(img, (cx, cy), int(max(tw, th) * 0.9) + 4, CANDIDATE_COLOR, -1, cv2.LINE_AA)
        cv2.putText(img, text, (cx - tw // 2, cy + th // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (20, 20, 20), 2, cv2.LINE_AA)
    return img


def draw_setup_points(frame: np.ndarray, points: list[tuple[float, float]]) -> np.ndarray:
    """Draw the corners clicked so far in the seat setup tool."""
    img = frame.copy()
    h, w = img.shape[:2]
    pts = [(int(x * w), int(y * h)) for x, y in points]
    for i, p in enumerate(pts):
        cv2.circle(img, p, 5, SETUP_COLOR, -1, cv2.LINE_AA)
        cv2.putText(img, str(i + 1), (p[0] + 6, p[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, SETUP_COLOR, 1, cv2.LINE_AA)
    if len(pts) >= 2:
        cv2.polylines(img, [np.array(pts, dtype=np.int32)], len(pts) >= 4, SETUP_COLOR, 2, cv2.LINE_AA)
    return img


def draw_numbered_seats(frame: np.ndarray, seats: Iterable[Seat], highlight: int | None = None) -> np.ndarray:
    """Seat polygons with big numbers (1, 2, 3...) and seat ids, in one neutral colour.

    Used by the labelling tool, so labellers see the seat areas but no detector output.
    """
    img = frame.copy()
    h, w = img.shape[:2]
    scale = max(0.6, min(1.6, max(w, h) / 900))
    for i, seat in enumerate(seats):
        if len(seat.polygon) < 3:
            continue
        pts = _to_px(seat.polygon, w, h)
        thick = 4 if highlight == i else 2
        color = (255, 196, 0) if highlight == i else NUMBERED_COLOR
        cv2.polylines(img, [pts], True, color, thick, cv2.LINE_AA)
        cx, cy = int(pts[:, 0].mean()), int(pts[:, 1].mean())
        text = str(i + 1)
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.1 * scale, 3)
        cv2.circle(img, (cx, cy), int(max(tw, th) * 0.9), color, -1, cv2.LINE_AA)
        cv2.putText(img, text, (cx - tw // 2, cy + th // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.1 * scale,
                    (255, 255, 255), 3, cv2.LINE_AA)
        x, y = int(pts[:, 0].min()), int(pts[:, 1].min())
        _label(img, seat.seat_id, (x + 2, y + int(16 * scale)), color, 0.45 * scale)
    return img


def to_data_uri(frame: np.ndarray, quality: int = 80) -> str:
    """Encode an RGB frame as an in-memory JPEG data URL (never touches disk)."""
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("could not encode frame")
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


def placeholder(width: int = 640, height: int = 360, text: str = "No frame yet") -> np.ndarray:
    img = np.full((height, width, 3), 30, dtype=np.uint8)
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
    cv2.putText(img, text, ((width - tw) // 2, (height + th) // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2, cv2.LINE_AA)
    return img
