# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy",
#   "pydantic>=2.6",
#   "huggingface_hub>=0.30",
#   "torch",
#   "chronos-forecasting>=2.0",
# ]
#
# [[tool.uv.index]]
# name = "pytorch-cpu"
# url = "https://download.pytorch.org/whl/cpu"
# explicit = true
#
# [tool.uv.sources]
# torch = { index = "pytorch-cpu" }
# ///
"""Forecast backtest (CLAUDE.md section 8.3).

Holds out the last week of (synthetic, clearly labelled) history per venue and compares models on
MAE of free seats at 15, 30 and 60 minute horizons:

- persistence: free seats stay as they are now (naive reference)
- baseline: calendar-aware average by day type and 15-minute slot (the app default)
- blend: what the app shows, live count carried along the baseline trend (availability_at)
- chronos: amazon/chronos-bolt-small, zero-shot (optional, skipped gracefully if it can't load)

Run locally:   uv run jobs/backtest.py
Run as a Job:  hf jobs uv run --flavor cpu-basic --secrets HF_TOKEN jobs/backtest.py --push-to <user>/birdie-results
Results are written to JSON (jobs/results/backtest.json) and optionally pushed to a Hub dataset.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
HORIZONS_MIN = (15, 30, 60)


GITHUB_TARBALL = "https://github.com/Dzyreee/birdie/archive/refs/heads/main.tar.gz"


def import_birdie(space_id: str) -> Path:
    """Use the local checkout if there is one, else the Space, else the public GitHub repo."""
    if (ROOT / "birdie" / "__init__.py").exists():
        sys.path.insert(0, str(ROOT))
        return ROOT
    try:
        from huggingface_hub import snapshot_download

        path = Path(snapshot_download(repo_id=space_id, repo_type="space",
                                      allow_patterns=["birdie/**", "venues/*.json"]))
    except Exception as exc:
        import io
        import tarfile
        import tempfile
        import urllib.request

        url = os.getenv("BIRDIE_GITHUB_TARBALL", GITHUB_TARBALL)
        print(f"[backtest] Space {space_id} unavailable ({type(exc).__name__}); using {url}", flush=True)
        dest = Path(tempfile.mkdtemp(prefix="birdie-"))
        with urllib.request.urlopen(url) as resp:
            tarfile.open(fileobj=io.BytesIO(resp.read()), mode="r:gz").extractall(dest, filter="data")
        path = next(p for p in dest.iterdir() if (p / "birdie" / "__init__.py").exists())
    sys.path.insert(0, str(path))
    return path


def mae(errors: list[float]) -> float | None:
    return round(sum(errors) / len(errors), 3) if errors else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--end", default="2026-11-06T00:00:00+03:00", help="end of the synthetic history (ISO)")
    parser.add_argument("--weeks", type=int, default=4)
    parser.add_argument("--holdout-days", type=int, default=7)
    parser.add_argument("--origin-every", type=int, default=60, help="minutes between forecast origins")
    parser.add_argument("--no-chronos", action="store_true")
    parser.add_argument("--out", default=str(HERE / "results" / "backtest.json"))
    parser.add_argument("--push-to", default=os.getenv("BIRDIE_RESULTS_REPO"), help="Hub dataset repo id")
    parser.add_argument("--space-id", default=os.getenv("BIRDIE_SPACE_ID", "Dzyre/birdie"))
    args = parser.parse_args()

    started = time.time()
    root = import_birdie(args.space_id)
    from birdie.decision import blend_availability
    from birdie.forecast.model import BaselineForecaster, ForecasterUnavailable, ratio
    from birdie.forecast.synthetic import generate_history
    from birdie.venues import load_all

    end = datetime.fromisoformat(args.end)
    configs = load_all(root / "venues")
    chronos = None
    chronos_error = None
    if not args.no_chronos:
        try:
            from birdie.forecast.model import ChronosForecaster

            chronos = ChronosForecaster()
        except ForecasterUnavailable as exc:
            chronos_error = str(exc)
            print(f"[backtest] {exc}; continuing without Chronos", flush=True)

    steps = {h: h // 15 for h in HORIZONS_MIN}
    every = max(1, args.origin_every // 15)
    results: dict = {}
    pooled: dict[str, dict[int, list[float]]] = {}

    for vid, cfg in configs.items():
        n = len(cfg.seats)
        hist = generate_history(cfg.venue, n, end=end, weeks=args.weeks)
        split_ts = end - timedelta(days=args.holdout_days)
        split = next(i for i, r in enumerate(hist) if r["ts"] >= split_ts)
        model = BaselineForecaster(cfg.venue.type).fit(hist[:split])
        series = [ratio(r) for r in hist]
        max_step = max(steps.values())
        origins = [i for i in range(split, len(hist) - max_step) if (i - split) % every == 0]

        chronos_preds: dict[int, list[float]] = {}
        if chronos is not None:
            for start in range(0, len(origins), 64):
                batch = origins[start:start + 64]
                preds = chronos.predict([series[: i + 1] for i in batch], max_step)
                for i, p in zip(batch, preds):
                    chronos_preds[i] = p["median"]

        errors: dict[str, dict[int, list[float]]] = {
            m: {h: [] for h in HORIZONS_MIN} for m in ("persistence", "baseline", "blend", "chronos")
        }
        open_errors: dict[str, dict[int, list[float]]] = {
            m: {h: [] for h in HORIZONS_MIN} for m in ("persistence", "baseline", "blend", "chronos")
        }
        for i in origins:
            now_free = hist[i]["free"]
            b_now = n * (1 - model.predict_ratio(hist[i]["ts"]))
            for h, k in steps.items():
                target = hist[i + k]
                actual = target["free"]
                b_arr = n * (1 - model.predict_ratio(target["ts"]))
                preds = {
                    "persistence": now_free,
                    "baseline": b_arr,
                    "blend": blend_availability(venue_id=vid, total=n, live_free=now_free, forecast_free_now=b_now,
                                                forecast_free_arrival=b_arr, arrival_minutes=h).expected_free,
                }
                if i in chronos_preds:
                    preds["chronos"] = n * (1 - chronos_preds[i][k - 1])
                is_open = target["occupied"] > 0 or hist[i]["occupied"] > 0
                for m, p in preds.items():
                    err = abs(p - actual)
                    errors[m][h].append(err)
                    if is_open:
                        open_errors[m][h].append(err)
                    pooled.setdefault(m, {hh: [] for hh in HORIZONS_MIN})[h].append(err)

        results[vid] = {
            "venue": cfg.venue.name,
            "type": cfg.venue.type.value,
            "seats": n,
            "origins": len(origins),
            "mae_free_seats": {m: {f"{h}min": mae(errors[m][h]) for h in HORIZONS_MIN}
                               for m in errors if errors[m][HORIZONS_MIN[0]]},
            "mae_free_seats_open_hours": {m: {f"{h}min": mae(open_errors[m][h]) for h in HORIZONS_MIN}
                                          for m in open_errors if open_errors[m][HORIZONS_MIN[0]]},
        }
        print(f"[backtest] {vid}: {json.dumps(results[vid]['mae_free_seats'])}", flush=True)

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data": "SYNTHETIC history (labelled synthetic): calendar-shaped occupancy, 15-minute buckets",
        "history_end": end.isoformat(),
        "weeks": args.weeks,
        "holdout_days": args.holdout_days,
        "origin_every_minutes": args.origin_every,
        "horizons_minutes": list(HORIZONS_MIN),
        "metric": "mean absolute error of free seats",
        "models": {
            "persistence": "free seats stay as they are now",
            "baseline": "average by day type (weekday/Friday/Saturday) and 15-min slot, calendar-adjusted",
            "blend": "app availability_at: live count carried along the baseline trend, w = 0.5^(h/20 min)",
            "chronos": "amazon/chronos-bolt-small, zero-shot median" if chronos else f"skipped ({chronos_error or 'disabled'})",
        },
        "overall_mae_free_seats": {m: {f"{h}min": mae(v[h]) for h in HORIZONS_MIN} for m, v in pooled.items()},
        "venues": results,
        "runtime_seconds": round(time.time() - started, 1),
        "machine": {"python": platform.python_version(), "platform": platform.platform(),
                    "hf_job": bool(os.getenv("JOB_ID") or os.getenv("HF_JOB_ID"))},
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    print(f"[backtest] wrote {out_path}", flush=True)
    print(json.dumps(out["overall_mae_free_seats"], indent=2), flush=True)

    if args.push_to:
        from huggingface_hub import HfApi

        api = HfApi()
        api.create_repo(args.push_to, repo_type="dataset", exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for path_in_repo in (f"backtest/{stamp}.json", "backtest/latest.json"):
            api.upload_file(path_or_fileobj=out_path.read_bytes(), path_in_repo=path_in_repo,
                            repo_id=args.push_to, repo_type="dataset",
                            commit_message=f"Forecast backtest {stamp}")
        print(f"[backtest] pushed to https://huggingface.co/datasets/{args.push_to}", flush=True)


if __name__ == "__main__":
    main()
