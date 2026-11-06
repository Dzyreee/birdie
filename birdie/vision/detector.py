"""One detector for people and belongings: PekingU/rtdetr_r18vd (COCO classes).

`person` means occupied; the belongings classes can make a seat HELD. One model pass per frame.
Frames stay in memory: nothing here writes to disk or logs image data.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import numpy as np
from PIL import Image

from birdie.config import DETECTION_THRESHOLD, DETECTOR_MODEL_ID, MAX_FRAME_SIDE

log = logging.getLogger(__name__)

PERSON = "person"
CHAIR = "chair"
BELONGINGS = frozenset({"backpack", "handbag", "suitcase", "laptop", "cup", "bottle", "book", "cell phone"})
KEEP_LABELS = frozenset({PERSON, CHAIR}) | BELONGINGS

_load_lock = threading.Lock()
_infer_lock = threading.Lock()
_model: Any = None
_processor: Any = None


def resize_long_side(frame: np.ndarray | Image.Image, max_side: int = MAX_FRAME_SIDE) -> Image.Image:
    """RGB PIL image whose long side is at most `max_side` pixels."""
    img = frame if isinstance(frame, Image.Image) else Image.fromarray(np.asarray(frame))
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    scale = max_side / max(w, h)
    if scale < 1.0:
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.BILINEAR)
    return img


def is_loaded() -> bool:
    return _model is not None


def load() -> tuple[Any, Any]:
    """Load the model once (CUDA if available, otherwise CPU). Safe to call many times."""
    global _model, _processor
    if _model is not None:
        return _model, _processor
    with _load_lock:
        if _model is None:
            import torch
            from transformers import AutoImageProcessor, RTDetrForObjectDetection

            device = "cuda" if torch.cuda.is_available() else "cpu"
            processor = AutoImageProcessor.from_pretrained(DETECTOR_MODEL_ID)
            model = RTDetrForObjectDetection.from_pretrained(DETECTOR_MODEL_ID).to(device).eval()
            _processor, _model = processor, model
            log.info("Loaded %s on %s", DETECTOR_MODEL_ID, device)
    return _model, _processor


def _gpu(fn):
    """Wrap with @spaces.GPU when the `spaces` package is importable (ZeroGPU). No-op otherwise.

    On ZeroGPU the wrapped function runs in a separate worker process, so it must stay pure:
    frame in, detections out. Seat state is never touched inside it.
    """
    try:
        import spaces  # type: ignore

        return spaces.GPU(duration=20)(fn)
    except Exception:  # not installed, or not on a Space
        return fn


@_gpu
def _infer(image: Image.Image, threshold: float) -> list[dict]:
    """Pure function: an RGB image in, detections out (pixel boxes in this image)."""
    import torch

    model, processor = load()
    inputs = processor(images=image, return_tensors="pt").to(model.device)
    with torch.inference_mode():
        outputs = model(**inputs)
    result = processor.post_process_object_detection(
        outputs, target_sizes=[(image.height, image.width)], threshold=threshold
    )[0]
    id2label = model.config.id2label
    detections = []
    for score, label_id, box in zip(
        result["scores"].tolist(), result["labels"].tolist(), result["boxes"].tolist()
    ):
        label = id2label.get(int(label_id), str(label_id))
        if label in KEEP_LABELS:
            x1, y1, x2, y2 = (max(0.0, float(v)) for v in box)
            detections.append(
                {
                    "label": label,
                    "score": round(float(score), 3),
                    "box": [round(x1, 1), round(y1, 1), round(min(x2, image.width), 1), round(min(y2, image.height), 1)],
                }
            )
    return detections


def detect(frame: np.ndarray | Image.Image, threshold: float = DETECTION_THRESHOLD) -> list[dict]:
    """Detect chairs, people and belongings.

    Returns [{label, score, box}] where box = [x1, y1, x2, y2] in pixel coordinates of the
    frame you passed in. The frame is resized internally so its long side is <= 640 px.
    """
    original = frame if isinstance(frame, Image.Image) else Image.fromarray(np.asarray(frame))
    small = resize_long_side(original)
    with _infer_lock:  # one inference at a time keeps CPU latency predictable
        detections = _infer(small, threshold)
    sx = original.width / small.width
    sy = original.height / small.height
    if sx != 1.0 or sy != 1.0:
        for d in detections:
            x1, y1, x2, y2 = d["box"]
            d["box"] = [round(x1 * sx, 1), round(y1 * sy, 1), round(x2 * sx, 1), round(y2 * sy, 1)]
    return detections
