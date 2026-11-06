"""Sample a recorded clip at about 1 frame per second, in memory."""

from __future__ import annotations

from collections.abc import Iterator
from math import isfinite

import cv2
import numpy as np

from birdie.config import TARGET_FPS


def iter_clip_frames(path: str, fps: float = TARGET_FPS) -> Iterator[tuple[float, np.ndarray]]:
    """Yield (seconds_into_clip, RGB frame) at `fps`. Frames are never written anywhere."""
    if not isfinite(fps) or fps <= 0:
        raise ValueError("sampling fps must be positive")
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError("could not open the video clip")
    try:
        native = cap.get(cv2.CAP_PROP_FPS)
        if not isfinite(native) or native <= 0:
            native = 25.0
        reported_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        step = max(1, int(round(native / fps)))
        index = 0
        yielded = False
        while True:
            ok = cap.grab()
            if not ok:
                if reported_frames and index < reported_frames - 1:
                    raise ValueError(f"video decoding failed near frame {index}")
                break
            if index % step == 0:
                ok, bgr = cap.retrieve()
                if not ok:
                    raise ValueError(f"video decoding failed at frame {index}")
                if bgr is None or bgr.ndim != 3 or bgr.shape[0] == 0 or bgr.shape[1] == 0:
                    raise ValueError(f"video frame {index} is invalid")
                yielded = True
                yield index / native, cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            index += 1
        if not yielded:
            raise ValueError("the video contains no decodable frames")
    finally:
        cap.release()
