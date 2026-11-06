import cv2
import numpy as np
import pytest

from birdie.vision.clip import iter_clip_frames


class FakeCapture:
    def __init__(self, frames, fps=2.0, fail_at=None):
        self.frames = frames
        self.fps = fps
        self.fail_at = fail_at
        self.index = -1
        self.retrieved = False

    def isOpened(self):
        return True

    def get(self, prop):
        if prop == cv2.CAP_PROP_FPS:
            return self.fps
        if prop == cv2.CAP_PROP_FRAME_COUNT:
            return len(self.frames)
        return 0

    def grab(self):
        if self.fail_at is not None and self.index + 1 == self.fail_at:
            return False
        if self.index + 1 >= len(self.frames):
            return False
        self.index += 1
        self.retrieved = False
        return True

    def retrieve(self):
        self.retrieved = True
        return True, self.frames[self.index]

    def release(self):
        pass


def test_clip_samples_rgb_frames_with_source_timestamps(monkeypatch):
    frames = [np.full((2, 3, 3), (1, 2, 3), dtype=np.uint8) for _ in range(5)]
    monkeypatch.setattr(cv2, "VideoCapture", lambda path: FakeCapture(frames, fps=2.0))
    sampled = list(iter_clip_frames("fake.mp4", fps=1.0))
    assert [t for t, _ in sampled] == [0.0, 1.0, 2.0]
    assert tuple(sampled[0][1][0, 0]) == (3, 2, 1)


def test_corrupt_clip_fails_instead_of_looking_like_an_empty_room(monkeypatch):
    frames = [np.zeros((2, 3, 3), dtype=np.uint8) for _ in range(5)]
    monkeypatch.setattr(cv2, "VideoCapture", lambda path: FakeCapture(frames, fail_at=2))
    with pytest.raises(ValueError, match="decoding failed"):
        list(iter_clip_frames("corrupt.mp4"))


def test_clip_rejects_invalid_sampling_rate(monkeypatch):
    with pytest.raises(ValueError, match="fps"):
        list(iter_clip_frames("fake.mp4", fps=0))
