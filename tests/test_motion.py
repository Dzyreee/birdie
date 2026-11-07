import cv2
import numpy as np

from birdie.vision.motion import FrameAligner, warp_polygon


def textured(seed=0, size=(480, 640)):
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 255, (size[0] // 8, size[1] // 8, 3), dtype=np.uint8)
    img = cv2.resize(img, (size[1], size[0]), interpolation=cv2.INTER_CUBIC)
    return cv2.GaussianBlur(img, (0, 0), 1.2)


def shifted(img, dx, dy):
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]), borderMode=cv2.BORDER_REFLECT)


def test_aligner_follows_a_camera_pan():
    ref = textured()
    al = FrameAligner()
    assert np.allclose(al.update(ref), np.eye(3))  # first frame is the reference
    h = al.update(shifted(ref, 32, 24))  # camera drifted: the picture moved by (32, 24) px
    box = [(0.25, 0.25), (0.5, 0.25), (0.5, 0.5), (0.25, 0.5)]
    out = warp_polygon(box, h)
    assert np.allclose(out[0], (0.25 + 32 / 640, 0.25 + 24 / 480), atol=0.01)
    assert al.last_inliers > 50


def test_aligner_keeps_last_transform_when_a_frame_cannot_be_matched():
    ref = textured()
    al = FrameAligner()
    al.update(ref)
    good = al.update(shifted(ref, 16, 0))
    blank = np.zeros_like(ref)
    assert np.allclose(al.update(blank), good)  # no features: reuse the last good transform
    al.reset()
    assert not al.has_reference and np.allclose(al.update(blank), np.eye(3))


