# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy",
#   "pillow",
#   "pydantic>=2.6",
#   "shapely>=2.0",
#   "huggingface_hub>=0.30",
# ]
# ///
"""Seat-state accuracy evaluation (CLAUDE.md section 8.7).

Reads labelled clips (eval_data/<clip_id>/: seats, per-frame detections, labels) from a local folder or a
Hub dataset repo and reports observation accuracy and seat-state accuracy, per clip and overall, with
confusion matrices and the worst frames. The detector already ran on the original frames in memory at
extraction time (originals are never stored), so this job only needs the stored detections: no model,
no GPU, a few seconds on cpu-basic.

Run locally:   uv run jobs/evaluate.py                      (reads eval_data/)
From the Hub:  uv run jobs/evaluate.py --dataset <user>/birdie-eval --push
As an HF Job:  scripts/run_eval_job.sh <user>/birdie-eval
Outputs: results.json and results.md (default eval_data/results/), optionally pushed to the dataset under results/.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GITHUB_TARBALL = "https://github.com/Dzyreee/birdie/archive/refs/heads/main.tar.gz"


def import_birdie() -> Path:
    """Use the local checkout if there is one, else the public GitHub repo (main), else the Space."""
    if (ROOT / "birdie" / "evaluation.py").exists():
        sys.path.insert(0, str(ROOT))
        return ROOT
    import io
    import tarfile
    import tempfile
    import urllib.request

    url = os.getenv("BIRDIE_GITHUB_TARBALL", GITHUB_TARBALL)
    try:
        dest = Path(tempfile.mkdtemp(prefix="birdie-"))
        with urllib.request.urlopen(url, timeout=60) as resp:
            tarfile.open(fileobj=io.BytesIO(resp.read()), mode="r:gz").extractall(dest, filter="data")
        path = next(p for p in dest.iterdir() if (p / "birdie" / "evaluation.py").exists())
    except Exception as exc:
        from huggingface_hub import snapshot_download

        space = os.getenv("BIRDIE_SPACE_ID", "Affaad/birdie")
        print(f"[evaluate] {url} unavailable ({type(exc).__name__}); trying Space {space}", flush=True)
        path = Path(snapshot_download(repo_id=space, repo_type="space", allow_patterns=["birdie/**"]))
    sys.path.insert(0, str(path))
    return path


def fetch_dataset(repo_id: str) -> Path:
    from huggingface_hub import snapshot_download

    return Path(snapshot_download(
        repo_id=repo_id, repo_type="dataset",
        allow_patterns=["*/seats.json", "*/meta.json", "*/labels.jsonl", "*/frames/*.json"],  # no images needed
    ))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default=str(ROOT / "eval_data"), help="local eval_data folder")
    parser.add_argument("--dataset", default=os.getenv("BIRDIE_EVAL_DATASET"), help="Hub dataset repo id")
    parser.add_argument("--out", default=None, help="output folder (default <data>/results)")
    parser.add_argument("--threshold", type=float, default=None, help="detector score threshold (default: app's)")
    parser.add_argument("--worst", type=int, default=10, help="how many worst frames to list")
    parser.add_argument("--push", action="store_true", help="push results to the dataset repo under results/")
    args = parser.parse_args()

    started = time.time()
    import_birdie()
    from birdie.config import DEMO_TIMERS, DETECTION_THRESHOLD
    from birdie.evaluation import evaluate, list_clip_dirs, load_clip, results_markdown

    data = fetch_dataset(args.dataset) if args.dataset else Path(args.data)
    clip_dirs = list_clip_dirs(data)
    clips = [c for c in (load_clip(d) for d in clip_dirs) if c.seats and c.labels]
    if not clips:
        sys.exit(f"No labelled clips found in {args.dataset or data}")

    threshold = DETECTION_THRESHOLD if args.threshold is None else args.threshold
    results = evaluate(clips, threshold=threshold, k=DEMO_TIMERS.smoothing_frames,
                       hold_seconds=DEMO_TIMERS.hold_seconds, worst=args.worst)
    results = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_source": f"hf://datasets/{args.dataset}" if args.dataset else str(data),
        "note": "Frames stored with people pixelated; the detector (PekingU/rtdetr_r18vd) ran on the original "
                "frames in memory at extraction. States replayed through birdie/vision/state.py with the demo timers.",
        **results,
        "runtime_seconds": round(time.time() - started, 2),
        "machine": {"python": platform.python_version(), "platform": platform.platform(),
                    "hf_job": bool(os.getenv("JOB_ID") or os.getenv("HF_JOB_ID"))},
    }

    out = Path(args.out) if args.out else (Path("results") if args.dataset else data / "results")
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    (out / "results.md").write_text(results_markdown(results), encoding="utf-8")
    o, s = results["observations"], results["states"]
    print(f"[evaluate] {len(clips)} clips · observation accuracy {o['accuracy']} on {o['n']} · "
          f"seat-state accuracy {s['accuracy']} on {s['n']}", flush=True)
    print(f"[evaluate] wrote {out / 'results.json'} and {out / 'results.md'}", flush=True)

    if args.push:
        if not args.dataset:
            sys.exit("--push needs --dataset")
        from huggingface_hub import HfApi

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        api = HfApi()
        api.upload_folder(repo_id=args.dataset, repo_type="dataset", folder_path=str(out),
                          path_in_repo="results", allow_patterns=["results.json", "results.md"],
                          commit_message=f"Evaluation results {stamp}")
        print(f"[evaluate] pushed to https://huggingface.co/datasets/{args.dataset}/tree/main/results", flush=True)


if __name__ == "__main__":
    main()
