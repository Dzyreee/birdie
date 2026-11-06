"""A background thread that calls a function every few seconds."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, fn: Callable[[], object], interval_seconds: float = 2.0, name: str = "birdie-scheduler") -> None:
        self.fn = fn
        self.interval = interval_seconds
        self.name = name
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.fn()
            except Exception:  # keep ticking whatever happens
                log.exception("scheduler tick failed")
            self._stop.wait(self.interval)
