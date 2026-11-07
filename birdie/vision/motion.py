"""Camera-motion compensation for hand-held clips.

Seat outlines are drawn once, on the first frame of a clip. If the camera drifts (a phone held by hand), fixed
outlines slide off their chairs. FrameAligner keeps the first frame's feature points (in memory only, never
stored) and, for every later frame, estimates the homography that maps first-frame coordinates to that frame
(ORB features + RANSAC, so a moving person doesn't throw it off). Seat polygons are warped with it before the
seat assignment. If a frame can't be matched, the last good transform is reused.

Remove this module and the three lines that call it in birdie/service.py to go back to fixed outlines.
"""

from __future__ import annotations

import cv2
import numpy as np

MIN_INLIERS = 12
MAX_SIDE = 640  # features are computed on a copy at most this wide


class FrameAligner:
    def __init__(self) -> None:
        self._orb = cv2.ORB_create(nfeatures=1500)
        self._matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        self._ref_kp: list | None = None
        self._ref_des: np.ndarray | None = None
        self._last_h = np.eye(3)
        self.has_reference = False
        self.last_inliers = 0

    def reset(self) -> None:
        """Forget the reference: the next frame becomes the new one (call at the start of every clip loop)."""
        self._ref_kp = self._ref_des = None
        self._last_h = np.eye(3)
        self.has_reference = False
        self.last_inliers = 0

    def _features(self, rgb: np.ndarray):
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        h, w = gray.shape
        scale = min(1.0, MAX_SIDE / max(h, w))
        if scale < 1.0:
            gray = cv2.resize(gray, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
        kp, des = self._orb.detectAndCompute(gray, None)
        return kp, des, scale

    def update(self, rgb: np.ndarray) -> np.ndarray:
        """Feed a frame. The first one after reset() becomes the reference. Returns the 3x3 homography
        (reference -> this frame) in NORMALISED coordinates (0..1), identity if unknown."""
        kp, des, _ = self._features(rgb)
        if not self.has_reference:
            self._ref_kp, self._ref_des = kp, des
            self.has_reference = des is not None and len(kp) >= MIN_INLIERS
            return np.eye(3)
        if des is None or self._ref_des is None or len(kp) < MIN_INLIERS:
            return self._last_h
        matches = self._matcher.match(self._ref_des, des)
        if len(matches) < MIN_INLIERS:
            return self._last_h
        matches = sorted(matches, key=lambda m: m.distance)[:300]
        src = np.float32([self._ref_kp[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
        dst = np.float32([kp[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
        h_px, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
        if h_px is None or mask is None or int(mask.sum()) < MIN_INLIERS:
            return self._last_h
        # Reject wild transforms (a bad match set): a hand-held pan changes scale and perspective only a little.
        a = h_px[:2, :2]
        det = float(np.linalg.det(a))
        if not (0.6 < det < 1.6) or abs(h_px[2, 0]) > 5e-3 or abs(h_px[2, 1]) > 5e-3:
            return self._last_h
        self.last_inliers = int(mask.sum())
        h, w = rgb.shape[:2]
        scale = min(1.0, MAX_SIDE / max(h, w))
        sw, sh = w * scale, h * scale
        norm = np.diag([sw, sh, 1.0])  # normalised -> feature-image pixels
        self._last_h = np.linalg.inv(norm) @ h_px @ norm
        return self._last_h


def warp_polygon(polygon: list[tuple[float, float]], h: np.ndarray) -> list[tuple[float, float]]:
    """Apply a normalised homography to a polygon, clamped to the frame."""
    if not polygon:
        return polygon
    pts = np.float32(polygon).reshape(-1, 1, 2)
    out = cv2.perspectiveTransform(pts, h.astype(np.float64)).reshape(-1, 2)
    return [(float(min(1.0, max(0.0, x))), float(min(1.0, max(0.0, y)))) for x, y in out]
