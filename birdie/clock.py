"""Real and fake clocks. Everything time-based takes a clock, so tests never sleep."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Protocol

# Qatar is UTC+3 all year (no daylight saving), so a fixed offset is exact
# and avoids depending on the tz database.
DOHA_TZ = timezone(timedelta(hours=3), "AST")


class Clock(Protocol):
    def now(self) -> datetime: ...


class RealClock:
    """Wall-clock time in Doha."""

    def now(self) -> datetime:
        return datetime.now(DOHA_TZ)


class FakeClock:
    """A clock you move by hand. Thread-safe so it can drive the scheduler in tests."""

    def __init__(self, start: datetime | None = None) -> None:
        if start is None:
            start = datetime(2026, 11, 7, 10, 0, tzinfo=DOHA_TZ)  # a Saturday morning
        if start.tzinfo is None:
            start = start.replace(tzinfo=DOHA_TZ)
        self._now = start
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def advance(self, seconds: float = 0, **kwargs: float) -> datetime:
        """Move forward, e.g. advance(30) or advance(minutes=5)."""
        with self._lock:
            self._now = self._now + timedelta(seconds=seconds, **kwargs)
            return self._now

    def set(self, when: datetime) -> None:
        if when.tzinfo is None:
            when = when.replace(tzinfo=DOHA_TZ)
        with self._lock:
            self._now = when


def to_doha(dt: datetime) -> datetime:
    """Normalise any datetime to an aware Doha-time datetime."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=DOHA_TZ)
    return dt.astimezone(DOHA_TZ)
