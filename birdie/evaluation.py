"""Seat-state accuracy evaluation (CLAUDE.md section 8.7). Framework-free.

Dataset layout, one folder per clip (eval_data/ is gitignored; the Hub copy is a private dataset):

    eval_data/<clip_id>/
      meta.json               clip info, sampling interval, detector settings
      seats.json              {"clip_id": ..., "seats": [Seat, ...]}  (normalised polygons)
      frames/000000.jpg       the frame with people PIXELATED (originals are never written)
      frames/000000.json      {"frame_id", "t", "width", "height", "detections": [{label, score, box}]}
                              boxes normalised to 0..1, detector run on the original frame in memory
      labels.jsonl            append-only; the last line for a frame wins:
                              {"frame_id", "labels": {seat_id: person|items|empty|unclear}, "labeller", "saved_at"}
                              {"frame_id", "removed": true, ...}  (frame deleted, e.g. a person was not pixelated)

Two scores:
- observation accuracy: per labelled seat and frame, the detector's raw observation (PERSON / ITEMS / EMPTY,
  via the same seat assignment as the app) against the human label. Unclear labels are excluded.
- seat-state accuracy: the human observations and the detector's observations are each replayed through the
  real SeatStateMachine (birdie/vision/state.py) at the clip timestamps with the demo timers, and the resulting
  FREE / OCCUPIED / HELD states are compared.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from birdie.clock import DOHA_TZ, FakeClock
from birdie.config import DEMO_TIMERS, DETECTION_THRESHOLD
from birdie.models import Seat, SeatState
from birdie.vision.seats import assign_detections, observe
from birdie.vision.state import Observation, SeatStateMachine

LABELS = ("person", "items", "empty", "unclear")
LABEL_NAMES = {"person": "Person", "items": "Items only", "empty": "Empty", "unclear": "Unclear"}
NAME_TO_LABEL = {v: k for k, v in LABEL_NAMES.items()}
LABEL_TO_OBS = {"person": Observation.PERSON, "items": Observation.ITEMS, "empty": Observation.EMPTY}
OBS_CLASSES = [Observation.PERSON, Observation.ITEMS, Observation.EMPTY]
OBS_DISPLAY = {Observation.PERSON: "Person", Observation.ITEMS: "Items only", Observation.EMPTY: "Empty"}
STATE_CLASSES = [SeatState.FREE, SeatState.OCCUPIED, SeatState.HELD]
VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm")
_EPOCH = datetime(2026, 1, 1, tzinfo=DOHA_TZ)


# --- dataset layout and I/O ---------------------------------------------------------

def clip_id_from_path(path: str | Path) -> str:
    """A safe folder name from a clip file name, e.g. 'IMG_0042 (1).MOV' -> 'img_0042_1'."""
    stem = Path(path).stem.lower()
    return re.sub(r"[^a-z0-9]+", "_", stem).strip("_") or "clip"


def frame_id(index: int) -> str:
    return f"{index:06d}"


@dataclass
class FrameRecord:
    frame_id: str
    t: float  # seconds into the clip
    width: int
    height: int
    detections: list[dict]  # [{label, score, box: [x1, y1, x2, y2] normalised}]
    image_path: Path | None = None


@dataclass
class EvalClip:
    clip_id: str
    root: Path
    seats: list[Seat]
    frames: list[FrameRecord]
    labels: dict[str, dict[str, str]] = field(default_factory=dict)  # frame_id -> seat_id -> label
    removed: set[str] = field(default_factory=set)
    meta: dict = field(default_factory=dict)

    def frame_index(self, fid: str) -> int:
        return next(i for i, f in enumerate(self.frames) if f.frame_id == fid)


def seats_path(clip_dir: Path) -> Path:
    return Path(clip_dir) / "seats.json"


def labels_path(clip_dir: Path) -> Path:
    return Path(clip_dir) / "labels.jsonl"


def load_seats(clip_dir: Path) -> list[Seat]:
    path = seats_path(clip_dir)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Seat.model_validate(s) for s in data.get("seats", [])]


def save_seats(clip_dir: Path, clip_id: str, seats: list[Seat]) -> Path:
    clip_dir = Path(clip_dir)
    clip_dir.mkdir(parents=True, exist_ok=True)
    path = seats_path(clip_dir)
    payload = {"clip_id": clip_id, "seats": [s.model_dump(mode="json") for s in sorted(seats, key=lambda s: s.seat_id)]}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def read_labels(path: Path) -> tuple[dict[str, dict[str, str]], set[str]]:
    """Latest labels per frame and the set of removed frames. Bad lines are skipped."""
    labels: dict[str, dict[str, str]] = {}
    removed: set[str] = set()
    path = Path(path)
    if not path.exists():
        return labels, removed
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        fid = row.get("frame_id")
        if not fid:
            continue
        if row.get("removed"):
            removed.add(fid)
            labels.pop(fid, None)
            continue
        clean = {sid: lab for sid, lab in (row.get("labels") or {}).items() if lab in LABELS}
        labels[fid] = clean
        removed.discard(fid)
    return labels, removed


def _append(path: Path, row: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()


def append_labels(clip_dir: Path, fid: str, labels: dict[str, str], labeller: str = "") -> None:
    bad = {k: v for k, v in labels.items() if v not in LABELS}
    if bad:
        raise ValueError(f"unknown labels: {bad}")
    _append(labels_path(clip_dir), {
        "frame_id": fid, "labels": labels, "labeller": labeller,
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })


def append_removed(clip_dir: Path, fid: str, labeller: str = "", reason: str = "person not pixelated") -> None:
    _append(labels_path(clip_dir), {
        "frame_id": fid, "removed": True, "reason": reason, "labeller": labeller,
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })


def load_frames(clip_dir: Path) -> list[FrameRecord]:
    frames = []
    for path in sorted((Path(clip_dir) / "frames").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        img = path.with_suffix(".jpg")
        frames.append(FrameRecord(
            frame_id=data["frame_id"], t=float(data["t"]), width=int(data["width"]), height=int(data["height"]),
            detections=list(data.get("detections", [])), image_path=img if img.exists() else None,
        ))
    return sorted(frames, key=lambda f: f.t)


def load_clip(clip_dir: Path) -> EvalClip:
    clip_dir = Path(clip_dir)
    meta_file = clip_dir / "meta.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
    labels, removed = read_labels(labels_path(clip_dir))
    return EvalClip(
        clip_id=meta.get("clip_id", clip_dir.name), root=clip_dir, seats=load_seats(clip_dir),
        frames=load_frames(clip_dir), labels=labels, removed=removed, meta=meta,
    )


def list_clip_dirs(root: Path) -> list[Path]:
    root = Path(root)
    if not root.exists():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "frames").is_dir())


# --- observations ---------------------------------------------------------------------

def detector_observations(frame: FrameRecord, seats: list[Seat], threshold: float = DETECTION_THRESHOLD
                          ) -> dict[str, Observation]:
    """The app's own seat assignment on the stored (normalised) detections."""
    dets = [d for d in frame.detections if d["score"] >= threshold]
    return observe(assign_detections(dets, seats, (1, 1)))


def confusion(pairs: list[tuple[object, object]], classes: list) -> list[list[int]]:
    """Rows = truth, columns = prediction, in the order of `classes`."""
    index = {c: i for i, c in enumerate(classes)}
    matrix = [[0] * len(classes) for _ in classes]
    for truth, pred in pairs:
        if truth in index and pred in index:
            matrix[index[truth]][index[pred]] += 1
    return matrix


def accuracy(matrix: list[list[int]]) -> float | None:
    total = sum(sum(row) for row in matrix)
    return round(sum(matrix[i][i] for i in range(len(matrix))) / total, 4) if total else None


def per_class(matrix: list[list[int]], names: list[str]) -> dict[str, dict]:
    out = {}
    for i, name in enumerate(names):
        support = sum(matrix[i])
        predicted = sum(row[i] for row in matrix)
        out[name] = {
            "support": support,
            "recall": round(matrix[i][i] / support, 4) if support else None,
            "precision": round(matrix[i][i] / predicted, 4) if predicted else None,
        }
    return out


# --- state replay -------------------------------------------------------------------------

def replay_states(
    sequence: list[tuple[float, Observation]],
    k: int = DEMO_TIMERS.smoothing_frames,
    hold_seconds: float = DEMO_TIMERS.hold_seconds,
) -> list[SeatState]:
    """Feed (t, observation) pairs through the real SeatStateMachine on a fake clock.

    The machine starts from the first observation: belongings without a person are already HELD and start
    their real-time grace timer, while unclear evidence starts UNKNOWN.
    """
    if not sequence:
        return []
    first_t, first_obs = sequence[0]
    clock = FakeClock(_EPOCH + timedelta(seconds=first_t))
    initial = {
        Observation.EMPTY: SeatState.FREE,
        Observation.PERSON: SeatState.OCCUPIED,
        Observation.ITEMS: SeatState.HELD,
        Observation.UNKNOWN: SeatState.UNKNOWN,
    }[first_obs]
    machine = SeatStateMachine("eval", "seat", clock, k=k, hold_seconds=hold_seconds, initial=initial)
    states = []
    for t, obs in sequence:
        clock.set(_EPOCH + timedelta(seconds=t))
        machine.update(obs)
        states.append(machine.state)
    return states


# --- evaluation ---------------------------------------------------------------------------

@dataclass
class ClipResult:
    clip_id: str
    frames: int
    labelled_frames: int
    removed_frames: int
    unclear: int
    obs_pairs: list[tuple[Observation, Observation]]
    state_pairs: list[tuple[SeatState, SeatState]]
    frame_errors: list[dict]


def evaluate_clip(
    clip: EvalClip,
    threshold: float = DETECTION_THRESHOLD,
    k: int = DEMO_TIMERS.smoothing_frames,
    hold_seconds: float = DEMO_TIMERS.hold_seconds,
) -> ClipResult:
    frames = [f for f in clip.frames if f.frame_id in clip.labels and f.frame_id not in clip.removed]
    detected = {f.frame_id: detector_observations(f, clip.seats, threshold) for f in frames}
    obs_pairs: list[tuple[Observation, Observation]] = []
    state_pairs: list[tuple[SeatState, SeatState]] = []
    unclear = 0
    errors: dict[str, dict] = {
        f.frame_id: {"clip_id": clip.clip_id, "frame_id": f.frame_id, "t": f.t, "obs_errors": 0, "state_errors": 0,
                     "seats": [], "image": f"{clip.clip_id}/frames/{f.frame_id}.jpg"}
        for f in frames
    }

    for seat in clip.seats:
        sid = seat.seat_id
        # (frame_id, t, truth observation, detector observation, truth label was clear)
        rows: list[tuple[str, float, Observation, Observation, bool]] = []
        last_truth: Observation | None = None
        for f in frames:
            label = clip.labels[f.frame_id].get(sid)
            pred = detected[f.frame_id].get(sid, Observation.EMPTY)
            clear = label in LABEL_TO_OBS
            if clear:
                truth = LABEL_TO_OBS[label]
                last_truth = truth
                obs_pairs.append((truth, pred))
                if truth != pred:
                    errors[f.frame_id]["obs_errors"] += 1
                    errors[f.frame_id]["seats"].append(
                        {"seat_id": sid, "truth": OBS_DISPLAY[truth], "detector": OBS_DISPLAY[pred]}
                    )
            else:
                if label == "unclear":
                    unclear += 1
                truth = last_truth  # unclear or missing: carry the last clear label forward for the replay
            if truth is None:
                continue  # nothing known about this seat yet
            rows.append((f.frame_id, f.t, truth, pred, clear))
        if not rows:
            continue
        truth_states = replay_states([(t, tr) for _, t, tr, _, _ in rows], k, hold_seconds)
        pred_states = replay_states([(t, pr) for _, t, _, pr, _ in rows], k, hold_seconds)
        for (fid, _, _, _, clear), ts, ps in zip(rows, truth_states, pred_states):
            if not clear:
                continue  # only score states where the human label is clear
            state_pairs.append((ts, ps))
            if ts != ps:
                errors[fid]["state_errors"] += 1

    return ClipResult(
        clip_id=clip.clip_id,
        frames=len(clip.frames),
        labelled_frames=len(frames),
        removed_frames=len(clip.removed),
        unclear=unclear,
        obs_pairs=obs_pairs,
        state_pairs=state_pairs,
        frame_errors=[e for e in errors.values() if e["obs_errors"] or e["state_errors"]],
    )


def _block(pairs, classes, names) -> dict:
    m = confusion(pairs, classes)
    return {"n": len(pairs), "accuracy": accuracy(m), "confusion": {"labels": names, "matrix": m},
            "per_class": per_class(m, names)}


def evaluate(
    clips: list[EvalClip],
    threshold: float = DETECTION_THRESHOLD,
    k: int = DEMO_TIMERS.smoothing_frames,
    hold_seconds: float = DEMO_TIMERS.hold_seconds,
    worst: int = 10,
) -> dict:
    obs_names = [OBS_DISPLAY[c] for c in OBS_CLASSES]
    state_names = [s.value for s in STATE_CLASSES]
    per_clip = {}
    all_obs, all_states, all_errors = [], [], []
    totals = defaultdict(int)
    for clip in clips:
        r = evaluate_clip(clip, threshold, k, hold_seconds)
        all_obs += r.obs_pairs
        all_states += r.state_pairs
        all_errors += r.frame_errors
        for key in ("frames", "labelled_frames", "removed_frames", "unclear"):
            totals[key] += getattr(r, key)
        per_clip[clip.clip_id] = {
            "frames": r.frames,
            "labelled_frames": r.labelled_frames,
            "removed_frames": r.removed_frames,
            "seats": len(clip.seats),
            "unclear_excluded": r.unclear,
            "observations": {"n": len(r.obs_pairs), "accuracy": accuracy(confusion(r.obs_pairs, OBS_CLASSES))},
            "states": {"n": len(r.state_pairs), "accuracy": accuracy(confusion(r.state_pairs, STATE_CLASSES))},
        }
    worst_frames = sorted(all_errors, key=lambda e: (-e["obs_errors"], -e["state_errors"], e["clip_id"], e["t"]))
    return {
        "settings": {"detection_threshold": threshold, "smoothing_frames": k, "hold_seconds": hold_seconds},
        "totals": dict(totals) | {"clips": len(clips)},
        "observations": _block(all_obs, OBS_CLASSES, obs_names) | {"unclear_excluded": totals["unclear"]},
        "states": _block(all_states, STATE_CLASSES, state_names),
        "clips": per_clip,
        "worst_frames": worst_frames[:worst],
    }


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _matrix_md(block: dict) -> str:
    names = block["confusion"]["labels"]
    rows = ["| truth \\ predicted | " + " | ".join(names) + " |", "|---" * (len(names) + 1) + "|"]
    for name, row in zip(names, block["confusion"]["matrix"]):
        rows.append(f"| **{name}** | " + " | ".join(str(v) for v in row) + " |")
    return "\n".join(rows)


def results_markdown(results: dict) -> str:
    o, s, t = results["observations"], results["states"], results["totals"]
    st = results["settings"]
    lines = [
        "# Birdie seat-state evaluation",
        "",
        f"Generated {results.get('generated_at', '')}. Data: {results.get('data_source', '')}.",
        "",
        f"- Clips: {t['clips']} · frames: {t['frames']} · labelled frames: {t['labelled_frames']} "
        f"· removed frames: {t['removed_frames']}",
        f"- **Observation accuracy: {_pct(o['accuracy'])}** on {o['n']} seat-frames "
        f"(Unclear excluded: {o['unclear_excluded']})",
        f"- **Seat-state accuracy: {_pct(s['accuracy'])}** on {s['n']} seat-frames "
        f"(replayed through the app's state machine: k={st['smoothing_frames']} frames, "
        f"hold {st['hold_seconds']} s, detector threshold {st['detection_threshold']})",
        "",
        "Frames are stored with people pixelated; the detector ran on the original frames in memory at extraction.",
        "",
        "## Observations (Person / Items only / Empty)",
        "",
        _matrix_md(o),
        "",
        "| class | support | recall | precision |",
        "|---|---|---|---|",
    ]
    for name, m in o["per_class"].items():
        lines.append(f"| {name} | {m['support']} | {_pct(m['recall'])} | {_pct(m['precision'])} |")
    lines += ["", "## Seat states (FREE / OCCUPIED / HELD)", "", _matrix_md(s), "", "## Per clip", "",
              "| clip | seats | labelled frames | observation acc. | state acc. | unclear |", "|---|---|---|---|---|---|"]
    for cid, c in results["clips"].items():
        lines.append(f"| {cid} | {c['seats']} | {c['labelled_frames']} | {_pct(c['observations']['accuracy'])} "
                     f"| {_pct(c['states']['accuracy'])} | {c['unclear_excluded']} |")
    lines += ["", "## Worst frames (honest failure cases)", ""]
    if not results["worst_frames"]:
        lines.append("No errors.")
    for e in results["worst_frames"]:
        detail = ", ".join(f"{x['seat_id']}: {x['truth']} → {x['detector']}" for x in e["seats"]) or "state lag only"
        lines.append(f"- `{e['image']}` (t={e['t']:.0f} s): {e['obs_errors']} observation errors, "
                     f"{e['state_errors']} state errors. {detail}")
    return "\n".join(lines) + "\n"
