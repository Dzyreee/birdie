#!/usr/bin/env python3
"""Smoke test for the live Birdie Space. GET requests only, standard library only.

    python scripts/smoke_test.py                                  # https://affaad-birdie.hf.space
    python scripts/smoke_test.py https://affaad-birdie.hf.space --slow 3.0

Checks (CLAUDE.md section 7.2): the mobile app loads, /api/venues lists the 7 venues in the contract shape,
every /api/venues/{id} has a floor plan and seats with valid statuses, the operator console loads.
Prints one line per check with the response time, and exits 1 if any check fails.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

DEFAULT_URL = "https://affaad-birdie.hf.space"
EXPECTED_VENUES = {"nestwork-msheireb", "qnl", "qu-library", "qahwa-corner", "corniche-cup", "nakheel-study",
                   "waab-study-hall"}
VENUE_KEYS = {"venue_id", "name", "area", "type", "lat", "lon", "source", "drive_minutes", "open_until", "open_late",
              "amenities", "zones", "counts", "camera_online"}
SEAT_KEYS = {"seat_id", "table_id", "has_outlet", "has_window", "plan_x", "plan_y", "plan_rot", "status", "since"}
TYPES = {"library", "cafe", "cowork", "study_room"}
SOURCES = {"live", "recorded", "simulated"}
STATUSES = {"free", "taken", "held"}

results: list[tuple[str, bool, float, str]] = []


def get(url: str, timeout: float = 60.0) -> tuple[int, bytes, float]:
    """GET a URL. Returns (status, body, seconds). Never raises on HTTP errors."""
    start = time.perf_counter()
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "birdie-smoke-test"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), time.perf_counter() - start
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), time.perf_counter() - start
    except Exception as exc:  # DNS, timeout, connection refused...
        return 0, str(exc).encode(), time.perf_counter() - start


def record(name: str, ok: bool, secs: float, detail: str = "") -> None:
    results.append((name, ok, secs, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {secs:6.2f}s  {name}" + (f"  ({detail})" if detail else ""), flush=True)


def check_page(base: str, path: str, must_contain: str | None = None) -> None:
    status, body, secs = get(base + path)
    text = body.decode("utf-8", "replace")
    ok = status == 200 and (must_contain is None or must_contain.lower() in text.lower())
    record(f"GET {path}", ok, secs, f"HTTP {status}" + ("" if ok or status != 200 else f", missing '{must_contain}'"))


def check_json(base: str, path: str) -> tuple[object | None, float]:
    status, body, secs = get(base + path)
    try:
        data = json.loads(body)
    except ValueError:
        record(f"GET {path}", False, secs, f"HTTP {status}, not JSON")
        return None, secs
    if status != 200:
        record(f"GET {path}", False, secs, f"HTTP {status}")
        return None, secs
    return data, secs


def check_venue_summary(v: dict) -> list[str]:
    problems = []
    if set(v) != VENUE_KEYS:
        problems.append(f"keys differ: missing {sorted(VENUE_KEYS - set(v))} extra {sorted(set(v) - VENUE_KEYS)}")
    if v.get("type") not in TYPES:
        problems.append(f"type {v.get('type')!r}")
    if v.get("source") not in SOURCES:
        problems.append(f"source {v.get('source')!r}")
    c = v.get("counts") or {}
    if set(c) != {"free", "taken", "held", "total"} or c.get("free", 0) + c.get("taken", 0) + c.get("held", 0) != c.get("total"):
        problems.append(f"counts {c}")
    cam = v.get("camera_online", "missing")
    if (v.get("source") == "simulated") != (cam is None) or cam not in (True, False, None):
        problems.append(f"camera_online {cam!r} for source {v.get('source')}")
    if not isinstance(v.get("drive_minutes"), int):
        problems.append("drive_minutes not an int")
    return problems


def check_seats(detail: dict) -> list[str]:
    problems = []
    plan = detail.get("floor_plan") or {}
    if not plan or not plan.get("tables") or plan.get("width") != 362:
        problems.append("floor plan missing or wrong width")
    seats = detail.get("seats") or []
    if not seats:
        problems.append("no seats")
    ids = [s.get("seat_id") for s in seats]
    if len(ids) != len(set(ids)):
        problems.append("duplicate seat ids")
    counts = {"free": 0, "taken": 0, "held": 0}
    for s in seats:
        if set(s) != SEAT_KEYS:
            problems.append(f"seat {s.get('seat_id')} keys {sorted(set(s) ^ SEAT_KEYS)}")
            break
        if s["status"] not in STATUSES:
            problems.append(f"seat {s['seat_id']} status {s['status']!r}")
            break
        counts[s["status"]] += 1
        try:
            if datetime.fromisoformat(s["since"]).tzinfo is None:
                problems.append(f"seat {s['seat_id']} 'since' has no timezone")
                break
        except ValueError:
            problems.append(f"seat {s['seat_id']} 'since' not ISO 8601")
            break
        if not all(isinstance(s[k], (int, float)) for k in ("plan_x", "plan_y", "plan_rot")):
            problems.append(f"seat {s['seat_id']} has no plan position")
            break
    summary = detail.get("counts") or {}
    if not problems and any(summary.get(k) != counts[k] for k in counts):
        problems.append(f"counts {summary} do not match seats {counts}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help=f"Space URL (default {DEFAULT_URL})")
    parser.add_argument("--slow", type=float, default=5.0, help="warn when a response takes longer than this (s)")
    args = parser.parse_args()
    base = args.url.rstrip("/")
    print(f"Birdie smoke test: {base}  ({datetime.now().astimezone().isoformat(timespec='seconds')})\n")

    # The first request can take about a minute if the Space was asleep.
    check_page(base, "/", "<title>Birdie")
    check_page(base, "/app.js")
    check_page(base, "/operator/", "gradio")

    venues, secs = check_json(base, "/api/venues")
    if isinstance(venues, list):
        ids = {v.get("venue_id") for v in venues}
        problems = []
        if ids != EXPECTED_VENUES:
            problems.append(f"venues differ: missing {sorted(EXPECTED_VENUES - ids)} extra {sorted(ids - EXPECTED_VENUES)}")
        for v in venues:
            problems += [f"{v.get('venue_id')}: {p}" for p in check_venue_summary(v)]
        record("GET /api/venues (7 venues, contract shape)", not problems, secs, "; ".join(problems[:3]))
        for vid in sorted(ids):
            detail, secs = check_json(base, f"/api/venues/{vid}")
            if isinstance(detail, dict):
                problems = [f"{p}" for p in check_venue_summary({k: v for k, v in detail.items() if k in VENUE_KEYS})]
                problems += check_seats(detail)
                n = len(detail.get("seats") or [])
                record(f"GET /api/venues/{vid}", not problems, secs, "; ".join(problems[:3]) or f"{n} seats")
    elif venues is not None:
        record("GET /api/venues", False, secs, "not a list")

    status, _, secs = get(base + "/api/venues/does-not-exist")
    record("GET /api/venues/does-not-exist -> 404", status == 404, secs, f"HTTP {status}")

    times = [r[2] for r in results]
    slow = [r for r in results if r[2] > args.slow]
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed; response time: "
          f"median {sorted(times)[len(times) // 2]:.2f}s, max {max(times):.2f}s")
    if slow:
        print(f"WARNING: slower than {args.slow:.0f}s: " + ", ".join(r[0] for r in slow))
    live = next((v for v in (venues or []) if isinstance(v, dict) and v.get("venue_id") == "nestwork-msheireb"), None)
    if live:
        print(f"Nestwork: camera_online={live.get('camera_online')} counts={live.get('counts')} "
              "(camera_online false is normal when no clip is playing)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
