"""Occupancy forecasters (CLAUDE.md section 8.3).

- BaselineForecaster (default): average occupancy by venue, day type (weekday / Friday / Saturday)
  and 15-minute slot, adjusted by the Ramadan and exam-season calendar flags.
- ChronosForecaster (optional): amazon/chronos-bolt-small. Fails gracefully: if it can't load,
  callers get ForecasterUnavailable and fall back to the baseline.
- ForecastEngine: per-venue forecasts for the app (synthetic history + live buckets).

Forecasts are occupancy ratios (0..1), so they survive seat layout edits.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np

from birdie.clock import Clock, to_doha
from birdie.config import BUCKET_MINUTES, CHRONOS_MODEL_ID, USE_CHRONOS
from birdie.forecast import calendar as cal
from birdie.forecast.synthetic import generate_history, profile
from birdie.models import Venue, VenueConfig, VenueType
from birdie.storage import bucket_start

log = logging.getLogger(__name__)


def ratio(row: dict) -> float:
    total = row.get("total") or 0
    if total <= 0:
        return 0.0
    return float(min(1.0, max(0.0, (row["occupied"] + row.get("held", 0)) / total)))


class BaselineForecaster:
    name = "baseline"

    def __init__(self, venue_type: VenueType | str) -> None:
        self.venue_type = venue_type
        self.table: dict[tuple[str, int], float] = {}
        self.slot_means: dict[int, float] = {}

    def fit(self, history: list[dict]) -> BaselineForecaster:
        cells: dict[tuple[str, int], list[float]] = defaultdict(list)
        slots: dict[int, list[float]] = defaultdict(list)
        rows = [r for r in history if not (cal.is_ramadan(r["ts"]) or cal.is_exam_season(r["ts"]))] or history
        for r in rows:
            key = (cal.day_type(r["ts"]), cal.slot_of(r["ts"], BUCKET_MINUTES))
            value = ratio(r)
            cells[key].append(value)
            slots[key[1]].append(value)
        self.table = {k: float(np.mean(v)) for k, v in cells.items()}
        self.slot_means = {k: float(np.mean(v)) for k, v in slots.items()}
        return self

    def predict_ratio(self, ts: datetime) -> float:
        ts = to_doha(ts)
        key = (cal.day_type(ts), cal.slot_of(ts, BUCKET_MINUTES))
        if key in self.table:
            base = self.table[key]
        elif key[1] in self.slot_means:
            base = self.slot_means[key[1]]
        else:
            base = profile(self.venue_type, ts, ramadan=False, exam=False)
        if cal.is_ramadan(ts) or cal.is_exam_season(ts):
            # History is mostly unflagged: scale by the calendar prior for this hour.
            neutral = profile(self.venue_type, ts, ramadan=False, exam=False)
            flagged = profile(self.venue_type, ts)
            base = base * flagged / neutral if neutral > 0.02 else flagged
        return float(min(1.0, max(0.0, base)))

    def predict(self, start: datetime, steps: int, step_minutes: int = BUCKET_MINUTES) -> list[float]:
        return [self.predict_ratio(start + timedelta(minutes=step_minutes * (i + 1))) for i in range(steps)]


class ForecasterUnavailable(RuntimeError):
    pass


class ChronosForecaster:
    """amazon/chronos-bolt-small on CPU. Raises ForecasterUnavailable if it can't load."""

    name = "chronos-bolt-small"
    max_context = 2048

    def __init__(self, model_id: str = CHRONOS_MODEL_ID, device: str = "cpu") -> None:
        try:
            from chronos import BaseChronosPipeline

            self.pipeline = BaseChronosPipeline.from_pretrained(model_id, device_map=device)
        except Exception as exc:  # missing package, no network, incompatible versions...
            raise ForecasterUnavailable(f"Chronos unavailable: {exc}") from exc

    def predict(self, contexts: list[list[float]], horizon_steps: int) -> list[dict]:
        """Batch forecast. Returns [{median, low, high}] lists of ratios per context."""
        import torch

        inputs = [torch.tensor(c[-self.max_context:], dtype=torch.float32) for c in contexts]
        quantiles, _mean = self.pipeline.predict_quantiles(
            inputs, prediction_length=horizon_steps, quantile_levels=[0.1, 0.5, 0.9]
        )
        q = quantiles.numpy().clip(0.0, 1.0)
        return [{"low": q[i, :, 0].tolist(), "median": q[i, :, 1].tolist(), "high": q[i, :, 2].tolist()}
                for i in range(q.shape[0])]


def load_chronos() -> ChronosForecaster | None:
    try:
        return ChronosForecaster()
    except ForecasterUnavailable as exc:
        log.warning("%s; using the baseline forecaster", exc)
        return None


class ForecastEngine:
    """Per-venue forecasts for the app: baseline by default, Chronos when enabled and loadable."""

    CHRONOS_HORIZON_STEPS = 16  # 4 hours of 15-minute buckets
    CHRONOS_REFRESH = timedelta(minutes=15)

    def __init__(
        self,
        configs: dict[str, VenueConfig],
        clock: Clock,
        repo=None,
        use_chronos: bool = USE_CHRONOS,
    ) -> None:
        self.configs = configs
        self.clock = clock
        self.repo = repo
        self._lock = threading.Lock()
        now = clock.now()
        self.history: dict[str, list[dict]] = {}
        self.models: dict[str, BaselineForecaster] = {}
        for vid, cfg in configs.items():
            self.history[vid] = generate_history(cfg.venue, max(1, len(cfg.seats)), end=now)
            self.models[vid] = BaselineForecaster(cfg.venue.type).fit(self._full_history(vid))
        self.chronos = load_chronos() if use_chronos else None
        self._chronos_cache: dict[str, tuple[datetime, datetime, list[float]]] = {}

    @property
    def model_name(self) -> str:
        return ChronosForecaster.name if self.chronos else BaselineForecaster.name

    def venue(self, venue_id: str) -> Venue:
        return self.configs[venue_id].venue

    def _live_rows(self, venue_id: str) -> list[dict]:
        if self.repo is None:
            return []
        return [
            {"ts": b["ts"], "occupied": b["occupied"], "held": b["held"], "total": b["total"]}
            for b in self.repo.occupancy_buckets(venue_id)
        ]

    def _full_history(self, venue_id: str) -> list[dict]:
        """Synthetic history with live buckets replacing synthetic ones at the same time."""
        live = {r["ts"]: r for r in self._live_rows(venue_id)}
        rows = [r for r in self.history[venue_id] if r["ts"] not in live]
        return sorted(rows + list(live.values()), key=lambda r: r["ts"])

    def refit(self) -> None:
        """Fold live buckets into the baseline (cheap; run every few minutes)."""
        with self._lock:
            for vid, cfg in self.configs.items():
                self.models[vid] = BaselineForecaster(cfg.venue.type).fit(self._full_history(vid))

    def ratio_at(self, venue_id: str, ts: datetime) -> float:
        """Forecast occupancy ratio for `venue_id` at `ts`."""
        if self.chronos is not None:
            value = self._chronos_ratio(venue_id, ts)
            if value is not None:
                return value
        return self.models[venue_id].predict_ratio(ts)

    def _chronos_ratio(self, venue_id: str, ts: datetime) -> float | None:
        now = self.clock.now()
        try:
            with self._lock:
                cached = self._chronos_cache.get(venue_id)
                if cached is None or now - cached[0] > self.CHRONOS_REFRESH:
                    context = [ratio(r) for r in self._full_history(venue_id)]
                    [pred] = self.chronos.predict([context], self.CHRONOS_HORIZON_STEPS)
                    cached = (now, bucket_start(now), pred["median"])
                    self._chronos_cache[venue_id] = cached
            _, origin, values = cached
            steps = (to_doha(ts) - origin).total_seconds() / (BUCKET_MINUTES * 60)
            if steps < 1 or steps > len(values):
                return None
            return float(np.interp(steps, np.arange(1, len(values) + 1), values))
        except Exception:
            log.exception("Chronos forecast failed; falling back to the baseline")
            return None

    def typical_day(self, venue_id: str, day_type: str) -> list[tuple[float, float]]:
        """(hour, ratio) for every 15-minute slot of a day type, from the fitted baseline."""
        table = self.models[venue_id].table
        return [
            (slot * BUCKET_MINUTES / 60, table.get((day_type, slot), 0.0))
            for slot in range(24 * 60 // BUCKET_MINUTES)
        ]
