"""Draw seat states and detections on camera frames.

Frames are encoded to in-memory JPEG data URLs for the browser. Nothing is written to disk.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable

import cv2
import numpy as np

from birdie.models import Seat, SeatSnapshot, SeatState
from birdie.vision.detector import PERSON

# RGB colours
STATE_COLORS = {
    SeatState.UNKNOWN: (148, 163, 184),  # slate
    SeatState.FREE: (34, 197, 94),  # green
    SeatState.OCCUPIED: (239, 68, 68),  # red
    SeatState.HELD: (245, 158, 11),  # amber
}
BOX_PERSON = (148, 163, 184)
BOX_ITEM = (56, 189, 248)
SETUP_COLOR = (217, 70, 239)


def _to_px(poly: list[tuple[float, float]], w: int, h: int) -> np.ndarray:
    return np.array([[int(x * w), int(y * h)] for x, y in poly], dtype=np.int32)


def _label(img: np.ndarray, text: str, org: tuple[int, int], color: tuple[int, int, int], scale: float = 0.45) -> None:
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
    x, y = org
    y = max(th + 4, y)
    cv2.rectangle(img, (x, y - th - 4), (x + tw + 4, y + base - 2), color, -1)
    cv2.putText(img, text, (x + 2, y - 2), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 1, cv2.LINE_AA)


def annotate(
    frame: np.ndarray,
    seats: Iterable[Seat],
    snapshots: dict[str, SeatSnapshot],
    detections: list[dict],
    show_boxes: bool = True,
) -> np.ndarray:
    """RGB frame in, annotated RGB frame out."""
    img = frame.copy()
    h, w = img.shape[:2]
    overlay = img.copy()
    seats = list(seats)
    for seat in seats:
        if len(seat.polygon) < 3:
            continue
        snap = snapshots.get(seat.seat_id)
        color = STATE_COLORS[snap.state if snap else SeatState.UNKNOWN]
        cv2.fillPoly(overlay, [_to_px(seat.polygon, w, h)], color)
    img = cv2.addWeighted(overlay, 0.25, img, 0.75, 0)
    for seat in seats:
        if len(seat.polygon) < 3:
            continue
        snap = snapshots.get(seat.seat_id)
        state = snap.state if snap else SeatState.UNKNOWN
        pts = _to_px(seat.polygon, w, h)
        cv2.polylines(img, [pts], True, STATE_COLORS[state], 2, cv2.LINE_AA)
        x, y = pts[:, 0].min(), pts[:, 1].min()
        _label(img, f"{seat.seat_id} {state.value}", (int(x) + 2, int(y) + 16), STATE_COLORS[state])
    if show_boxes:
        for d in detections:
            x1, y1, x2, y2 = (int(v) for v in d["box"])
            color = BOX_PERSON if d["label"] == PERSON else BOX_ITEM
            cv2.rectangle(img, (x1, y1), (x2, y2), color, 1, cv2.LINE_AA)
            _label(img, f"{d['label']} {d['score']:.2f}", (x1, y2 + 14 if y2 + 14 < h else y1 + 14), color, 0.38)
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
