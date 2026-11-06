import importlib.util
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from birdie.evaluation import (
    EvalClip,
    FrameRecord,
    accuracy,
    append_labels,
    append_removed,
    clip_id_from_path,
    confusion,
    evaluate,
    evaluate_clip,
    load_clip,
    per_class,
    read_labels,
    replay_states,
    results_markdown,
    save_seats,
)
from birdie.models import Seat, SeatState
from birdie.vision.state import Observation

P, I, E = Observation.PERSON, Observation.ITEMS, Observation.EMPTY
LEFT = Seat(seat_id="L", venue_id="c", zone="seat", polygon=[(0, 0), (0.5, 0), (0.5, 1), (0, 1)])
RIGHT = Seat(seat_id="R", venue_id="c", zone="seat", polygon=[(0.5, 0), (1, 0), (1, 1), (0.5, 1)])
PERSON_LEFT = {"label": "person", "score": 0.9, "box": [0.1, 0.1, 0.4, 0.9]}
BAG_RIGHT = {"label": "backpack", "score": 0.8, "box": [0.6, 0.6, 0.8, 0.8]}


def frame(i, t, *dets):
    return FrameRecord(frame_id=f"{i:06d}", t=t, width=100, height=100, detections=list(dets))


def clip(frames, labels, removed=(), seats=(LEFT, RIGHT)):
    return EvalClip(clip_id="c", root=Path("."), seats=list(seats), frames=frames, labels=labels, removed=set(removed))


# --- metrics ----------------------------------------------------------------------------

def test_confusion_accuracy_and_per_class():
    pairs = [(P, P), (P, P), (I, P), (E, E), (E, I)]
    m = confusion(pairs, [P, I, E])
    assert m == [[2, 0, 0], [1, 0, 0], [0, 1, 1]]
    assert accuracy(m) == pytest.approx(3 / 5)
    pc = per_class(m, ["Person", "Items only", "Empty"])
    assert pc["Person"] == {"support": 2, "recall": 1.0, "precision": pytest.approx(2 / 3, abs=1e-4)}
    assert pc["Items only"]["recall"] == 0.0 and pc["Items only"]["precision"] == 0.0
    assert accuracy(confusion([], [P, I, E])) is None


# --- state replay ---------------------------------------------------------------------

def test_replay_belongings_become_held_after_hold_time():
    seq = [(0, P)] + [(t, I) for t in range(2, 42, 2)]
    states = replay_states(seq, k=3, hold_seconds=30)
    assert states[0] == SeatState.OCCUPIED
    # items first seen alone at t=2 -> HELD once t - 2 >= 30, i.e. from t=32 (index 16)
    assert states[15] == SeatState.OCCUPIED and states[16] == SeatState.HELD


def test_replay_starts_from_first_observation_and_smooths():
    assert replay_states([(0, P), (2, P)], k=3, hold_seconds=30) == [SeatState.OCCUPIED] * 2
    states = replay_states([(0, E), (2, P), (4, P), (6, P)], k=3, hold_seconds=30)
    assert states == [SeatState.FREE, SeatState.FREE, SeatState.FREE, SeatState.OCCUPIED]


# --- per-clip evaluation ----------------------------------------------------------------

def test_observation_accuracy_excludes_unclear_and_removed():
    frames = [frame(0, 0, PERSON_LEFT), frame(1, 2, PERSON_LEFT, BAG_RIGHT), frame(2, 4, PERSON_LEFT)]
    labels = {
        "000000": {"L": "person", "R": "empty"},
        "000001": {"L": "person", "R": "unclear"},
        "000002": {"L": "empty", "R": "empty"},
    }
    r = evaluate_clip(clip(frames, labels), k=1, hold_seconds=30)
    # 5 clear seat-frames; the detector disagrees only on L in frame 2 (truth empty, detector person)
    assert len(r.obs_pairs) == 5 and r.unclear == 1
    assert accuracy(confusion(r.obs_pairs, [P, I, E])) == pytest.approx(4 / 5)
    assert [e["frame_id"] for e in r.frame_errors] == ["000002"]

    r2 = evaluate_clip(clip(frames, labels, removed={"000002"}), k=1, hold_seconds=30)
    assert len(r2.obs_pairs) == 3 and r2.frame_errors == []


def test_state_accuracy_catches_missed_belongings():
    # A bag stays alone on R for 40 s. Humans see it; the detector misses it (no detections on R).
    frames = [frame(i, 2.0 * i) for i in range(21)]
    labels = {f.frame_id: {"R": "items"} for f in frames}
    r = evaluate_clip(clip(frames, labels, seats=[RIGHT]), k=3, hold_seconds=30)
    truth = [t for t, _ in r.state_pairs]
    pred = [p for _, p in r.state_pairs]
    assert truth[0] == SeatState.OCCUPIED and truth[-1] == SeatState.HELD
    assert set(pred) == {SeatState.FREE}
    assert accuracy(confusion(r.state_pairs, [SeatState.FREE, SeatState.OCCUPIED, SeatState.HELD])) == 0.0


def test_detector_items_observation_from_stored_boxes():
    frames = [frame(i, 2.0 * i, BAG_RIGHT) for i in range(3)]
    labels = {f.frame_id: {"L": "empty", "R": "items"} for f in frames}
    r = evaluate_clip(clip(frames, labels), k=3, hold_seconds=30)
    assert accuracy(confusion(r.obs_pairs, [P, I, E])) == 1.0
    assert accuracy(confusion(r.state_pairs, [SeatState.FREE, SeatState.OCCUPIED, SeatState.HELD])) == 1.0


def test_evaluate_report_and_worst_frames_order():
    frames = [frame(0, 0, PERSON_LEFT), frame(1, 2), frame(2, 4)]
    labels = {
        "000000": {"L": "person", "R": "empty"},
        "000001": {"L": "person", "R": "person"},  # detector sees nobody: 2 errors
        "000002": {"L": "person", "R": "empty"},  # 1 error
    }
    res = evaluate([clip(frames, labels)], k=1, hold_seconds=30, worst=5)
    assert [w["frame_id"] for w in res["worst_frames"]][:2] == ["000001", "000002"]
    assert res["worst_frames"][0]["obs_errors"] == 2
    assert res["observations"]["n"] == 6 and res["clips"]["c"]["labelled_frames"] == 3
    md = results_markdown(res | {"generated_at": "now", "data_source": "test"})
    assert "Observation accuracy" in md and "000001.jpg" in md


# --- dataset I/O ------------------------------------------------------------------------

def test_labels_file_latest_wins_and_removed(tmp_path):
    append_labels(tmp_path, "000000", {"S01": "person"}, "amal")
    append_labels(tmp_path, "000000", {"S01": "items"}, "amal")
    append_labels(tmp_path, "000001", {"S01": "empty"})
    append_removed(tmp_path, "000001")
    with open(tmp_path / "labels.jsonl", "a") as f:
        f.write("not json\n")
    labels, removed = read_labels(tmp_path / "labels.jsonl")
    assert labels == {"000000": {"S01": "items"}} and removed == {"000001"}
    with pytest.raises(ValueError):
        append_labels(tmp_path, "000002", {"S01": "chair"})


def test_load_clip_roundtrip(tmp_path):
    save_seats(tmp_path, "c", [LEFT])
    (tmp_path / "frames").mkdir()
    (tmp_path / "frames" / "000000.json").write_text(json.dumps(
        {"frame_id": "000000", "t": 0.0, "width": 10, "height": 10, "detections": [PERSON_LEFT]}))
    append_labels(tmp_path, "000000", {"L": "person"})
    c = load_clip(tmp_path)
    assert [s.seat_id for s in c.seats] == ["L"] and len(c.frames) == 1
    assert c.frames[0].image_path is None and c.labels == {"000000": {"L": "person"}}


def test_clip_id_from_path():
    assert clip_id_from_path("eval_clips/IMG_0042 (1).MOV") == "img_0042_1"
    assert clip_id_from_path("Table-3.mp4") == "table_3"


# --- extraction: originals never written, people pixelated ----------------------------------

def _load_extract_module():
    path = Path(__file__).resolve().parent.parent / "tools" / "extract_frames.py"
    spec = importlib.util.spec_from_file_location("extract_frames", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["extract_frames"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_extract_writes_only_pixelated_frames(tmp_path, monkeypatch):
    ex = _load_extract_module()
    yy, xx = np.mgrid[0:240, 0:320]
    checker = (((yy // 8) + (xx // 8)) % 2 * 255).astype(np.uint8)  # sharp detail everywhere
    original = np.dstack([checker] * 3)
    video = tmp_path / "clip.avi"
    w = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10, (320, 240))
    for _ in range(40):  # 4 seconds
        w.write(original)
    w.release()

    def fake_detect(frame):
        h, w_ = frame.shape[:2]
        return [{"label": "person", "score": 0.9, "box": [0.1 * w_, 0.1 * h, 0.5 * w_, 0.9 * h]}]

    monkeypatch.setattr(ex, "detect_original", fake_detect)
    out = ex.extract_clip(video, tmp_path / "eval", "c", seats=[LEFT], every=2.0, max_side=160)
    files = sorted(p.name for p in (out / "frames").iterdir())
    assert files == ["000000.jpg", "000000.json", "000001.jpg", "000001.json"]
    meta = json.loads((out / "meta.json").read_text())
    assert meta["originals_saved"] is False and meta["complete"] is True and meta["frames"] == 2
    rec = json.loads((out / "frames" / "000001.json").read_text())
    assert rec["t"] == pytest.approx(2.0) and rec["width"] == 160 and rec["height"] == 120
    assert rec["detections"][0]["box"] == pytest.approx([0.1, 0.1, 0.5, 0.9])

    saved = cv2.imread(str(out / "frames" / "000000.jpg"), cv2.IMREAD_GRAYSCALE)
    edges = cv2.Laplacian(saved, cv2.CV_64F)
    person = edges[30:90, 30:66]  # well inside the person box (x 16..80, y 12..108 at 160x120)
    background = edges[10:110, 110:150]  # far outside it
    # The checkerboard survives outside the person box and is wiped out inside it (pixelated + blurred).
    assert background.var() > 100 and person.var() < 0.05 * background.var()
    # Re-running does not redo a complete extraction.
    assert list(ex.iter_extract(video, tmp_path / "eval", "c", every=2.0)) == []
