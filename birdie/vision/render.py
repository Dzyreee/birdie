"""Draw object detections over camera frames without a seat map."""

from __future__ import annotations

import base64

import cv2
import numpy as np

from birdie.vision.detector import CHAIR, PERSON

BOX_PERSON = (148, 163, 184)
BOX_CHAIR = (34, 197, 94)
BOX_ITEM = (56, 189, 248)


def _label(img: np.ndarray, text: str, org: tuple[int, int], color: tuple[int, int, int], scale: float = 0.45) -> None:
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
    x, y = org
    y = max(th + 4, y)
    cv2.rectangle(img, (x, y - th - 4), (x + tw + 4, y + base - 2), color, -1)
    cv2.putText(img, text, (x + 2, y - 2), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 1, cv2.LINE_AA)


def annotate(frame: np.ndarray, detections: list[dict]) -> np.ndarray:
    """Return the RGB frame with only detector boxes and labels drawn on it."""
    img = frame.copy()
    h, w = img.shape[:2]
    for detection in detections:
        x1, y1, x2, y2 = (int(v) for v in detection["box"])
        color = BOX_PERSON if detection["label"] == PERSON else BOX_CHAIR if detection["label"] == CHAIR else BOX_ITEM
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)
        label_y = y2 + 14 if y2 + 14 < h else y1 + 14
        _label(img, f"{detection['label']} {detection['score']:.2f}", (x1, label_y), color, 0.45)
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


NUMBERED_COLOR = (56, 132, 255)  # neutral blue: no state or detector hint for labellers


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
