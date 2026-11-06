# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#   "torch",
#   "torchvision",
#   "transformers>=5.0,<6",
#   "pillow",
#   "numpy",
#   "shapely>=2.0",
#   "pydantic>=2.6",
#   "opencv-python-headless",
# ]
#
# [[tool.uv.index]]
# name = "pytorch-cpu"
# url = "https://download.pytorch.org/whl/cpu"
# explicit = true
#
# [tool.uv.sources]
# torch = { index = "pytorch-cpu" }
# torchvision = { index = "pytorch-cpu" }
# ///
"""Extract evaluation frames from a clip, with people pixelated.

For every sampled frame (one every 2 seconds by default) the Birdie detector runs on the ORIGINAL frame in
memory. Only a copy with people pixelated is written, plus the detections (normalised boxes) and the
timestamp. Original frames are never saved.

    uv run tools/extract_frames.py eval_clips/table1.mp4 --seats eval_data/table1/seats.json
    uv run tools/extract_frames.py eval_clips/table1.mp4            # reuses eval_data/<clip_id>/seats.json

Output: eval_data/<clip_id>/{meta.json, seats.json, frames/000000.jpg, frames/000000.json, ...}
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from birdie.config import DETECTOR_MODEL_ID  # noqa: E402
from birdie.evaluation import clip_id_from_path, frame_id, load_seats, save_seats  # noqa: E402
from birdie.models import Seat  # noqa: E402
from birdie.vision.clip import iter_clip_frames  # noqa: E402
from birdie.vision.render import blur_people  # noqa: E402

EVAL_ROOT = ROOT / "eval_data"
CLIPS_DIR = ROOT / "eval_clips"
SAVE_THRESHOLD = 0.15  # detections kept in the JSON (evaluation re-thresholds at the app's 0.4)
PIXELATE_THRESHOLD = 0.15  # people pixelated from this low score, to err on the side of privacy
PIXELATE_PAD = 0.2  # extra margin around each person box
DEFAULT_EVERY = 2.0
DEFAULT_MAX_SIDE = 960


def _resize(frame: np.ndarray, max_side: int) -> np.ndarray:
    h, w = frame.shape[:2]
    scale = max_side / max(h, w)
    if scale >= 1.0:
        return frame
    return cv2.resize(frame, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)


def pixelated_copy(frame: np.ndarray, detections_px: list[dict], extra_boxes_norm: list[list[float]] | None = None,
                   max_side: int = DEFAULT_MAX_SIDE) -> tuple[np.ndarray, list[list[float]]]:
    """Resize the original frame and pixelate every person (current boxes plus `extra_boxes_norm`).

    Returns the pixelated RGB copy and the normalised person boxes that were pixelated.
    """
    h, w = frame.shape[:2]
    persons = [
        [d["box"][0] / w, d["box"][1] / h, d["box"][2] / w, d["box"][3] / h]
        for d in detections_px if d["label"] == "person" and d["score"] >= PIXELATE_THRESHOLD
    ]
    small = _resize(frame, max_side)
    sh, sw = small.shape[:2]
    boxes = persons + list(extra_boxes_norm or [])
    px = [[b[0] * sw, b[1] * sh, b[2] * sw, b[3] * sh] for b in boxes]
    return blur_people(small, px, pad=PIXELATE_PAD), persons


def detect_original(frame: np.ndarray) -> list[dict]:
    """Run the Birdie detector on the original frame (in memory). Boxes in pixels of that frame."""
    from birdie.vision.detector import detect

    return detect(frame, threshold=SAVE_THRESHOLD)


def preview_frame(clip_path: str | Path, max_side: int = DEFAULT_MAX_SIDE) -> np.ndarray:
    """The clip's first frame with people pixelated, in memory only (used to draw seats)."""
    for _, frame in iter_clip_frames(str(clip_path), fps=1.0):
        pixelated, _ = pixelated_copy(frame, detect_original(frame), max_side=max_side)
        return pixelated
    raise ValueError("the clip has no frames")


def estimate_samples(clip_path: str | Path, every: float) -> int:
    cap = cv2.VideoCapture(str(clip_path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    finally:
        cap.release()
    return max(1, math.ceil(count / fps / every)) if count else 0


def iter_extract(
    clip_path: str | Path,
    out_root: str | Path = EVAL_ROOT,
    clip_id: str | None = None,
    seats: list[Seat] | None = None,
    every: float = DEFAULT_EVERY,
    max_side: int = DEFAULT_MAX_SIDE,
    force: bool = False,
) -> Iterator[tuple[int, int]]:
    """Extract frames, yielding (frames_done, estimated_total) as it goes."""
    clip_path = Path(clip_path)
    clip_id = clip_id or clip_id_from_path(clip_path)
    out = Path(out_root) / clip_id
    frames_dir = out / "frames"
    meta_path = out / "meta.json"
    if frames_dir.exists() and any(frames_dir.glob("*.json")):
        old = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        if not force:
            if old.get("every_seconds") not in (None, every):
                raise ValueError(f"{clip_id} was extracted every {old.get('every_seconds')} s; use force to redo it "
                                 "(labels are matched by frame number, so they would no longer line up)")
            if old.get("complete"):
                return  # already extracted
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)
    if seats:
        save_seats(out, clip_id, seats)

    total = estimate_samples(clip_path, every)
    meta = {
        "clip_id": clip_id,
        "source_name": clip_path.name,
        "every_seconds": every,
        "max_side": max_side,
        "detector": DETECTOR_MODEL_ID,
        "saved_detection_threshold": SAVE_THRESHOLD,
        "pixelate_threshold": PIXELATE_THRESHOLD,
        "originals_saved": False,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "complete": False,
    }
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    prev_persons: list[list[float]] = []
    n = 0
    for t, frame in iter_clip_frames(str(clip_path), fps=1.0 / every):
        h, w = frame.shape[:2]
        detections = detect_original(frame)  # original frame, in memory only
        # Also pixelate where people were in the previous sample, in case the detector misses someone now.
        pixelated, persons = pixelated_copy(frame, detections, prev_persons, max_side=max_side)
        prev_persons = persons
        del frame  # the original is never written anywhere
        fid = frame_id(n)
        ok, buf = cv2.imencode(".jpg", cv2.cvtColor(pixelated, cv2.COLOR_RGB2BGR), [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            raise RuntimeError("could not encode frame")
        (frames_dir / f"{fid}.jpg").write_bytes(buf.tobytes())
        record = {
            "frame_id": fid,
            "t": round(float(t), 3),
            "width": int(pixelated.shape[1]),
            "height": int(pixelated.shape[0]),
            "detections": [
                {"label": d["label"], "score": d["score"],
                 "box": [round(d["box"][0] / w, 5), round(d["box"][1] / h, 5),
                         round(d["box"][2] / w, 5), round(d["box"][3] / h, 5)]}
                for d in detections
            ],
        }
        (frames_dir / f"{fid}.json").write_text(json.dumps(record) + "\n", encoding="utf-8")
        n += 1
        yield n, max(total, n)
    meta.update({"frames": n, "complete": True})
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def extract_clip(clip_path, out_root=EVAL_ROOT, clip_id=None, seats=None, every=DEFAULT_EVERY,
                 max_side=DEFAULT_MAX_SIDE, force=False, on_progress: Callable[[int, int], None] | None = None) -> Path:
    clip_id = clip_id or clip_id_from_path(clip_path)
    for done, total in iter_extract(clip_path, out_root, clip_id, seats, every, max_side, force):
        if on_progress:
            on_progress(done, total)
    return Path(out_root) / clip_id


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("clip", help="video file (mp4, mov, ...)")
    p.add_argument("--seats", help="seat layout JSON (default: eval_data/<clip_id>/seats.json)")
    p.add_argument("--clip-id", help="folder name (default: from the file name)")
    p.add_argument("--every", type=float, default=DEFAULT_EVERY, help="seconds between frames (default 2)")
    p.add_argument("--max-side", type=int, default=DEFAULT_MAX_SIDE, help="long side of saved frames (default 960)")
    p.add_argument("--out", default=str(EVAL_ROOT), help="output root (default eval_data/)")
    p.add_argument("--force", action="store_true", help="re-extract even if frames exist")
    args = p.parse_args()

    clip_id = args.clip_id or clip_id_from_path(args.clip)
    out = Path(args.out) / clip_id
    if args.seats:
        data = json.loads(Path(args.seats).read_text(encoding="utf-8"))
        seats = [Seat.model_validate(s | {"venue_id": clip_id}) for s in data.get("seats", data)]
    else:
        seats = load_seats(out)
        if not seats:
            sys.exit(f"No seat layout: pass --seats or draw the seats in the label app first ({out / 'seats.json'})")
    extract_clip(args.clip, args.out, clip_id, seats, args.every, args.max_side, args.force,
                 on_progress=lambda d, t: print(f"\r{clip_id}: {d}/{t} frames", end="", flush=True))
    print(f"\nWrote {out} (people pixelated; originals not saved)")


if __name__ == "__main__":
    main()
