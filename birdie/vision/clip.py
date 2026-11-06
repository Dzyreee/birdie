"""Sample a recorded clip at about 1 frame per second, in memory."""

from __future__ import annotations

from collections.abc import Iterator

import cv2
import numpy as np

from birdie.config import TARGET_FPS


def iter_clip_frames(path: str, fps: float = TARGET_FPS) -> Iterator[tuple[float, np.ndarray]]:
    """Yield (seconds_into_clip, RGB frame) at `fps`. Frames are never written anywhere."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError("could not open the video clip")
    try:
        native = cap.get(cv2.CAP_PROP_FPS) or 25.0
        step = max(1, int(round(native / fps)))
        index = 0
        while True:
            ok = cap.grab()
            if not ok:
                break
            if index % step == 0:
                ok, bgr = cap.retrieve()
                if not ok:
                    break
                yield index / native, cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            index += 1
    finally:
        cap.release()
