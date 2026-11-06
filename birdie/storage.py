"""SQLite repository for seat events, occupancy buckets and staff alerts.

One connection shared across threads behind a lock (the Gradio workers and the
background scheduler all write here). Source camera frames are never stored in this database.
Use Repository(":memory:") in tests.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from birdie.clock import to_doha
from birdie.config import BUCKET_MINUTES, DB_PATH
from birdie.models import SeatEvent, SeatSnapshot, SeatState

SCHEMA = """
CREATE TABLE IF NOT EXISTS seat_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    venue_id TEXT NOT NULL,
    seat_id TEXT NOT NULL,
    old_state TEXT,
    new_state TEXT NOT NULL,
    synthetic INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_seat_events_venue_ts ON seat_events (venue_id, ts);

CREATE TABLE IF NOT EXISTS seat_status (
    venue_id TEXT NOT NULL,
    seat_id TEXT NOT NULL,
    state TEXT NOT NULL,
    state_changed_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    person_detected INTEGER,
    belongings_detected INTEGER,
    confidence REAL,
    unattended_since TEXT,
    manual_override INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (venue_id, seat_id)
);

CREATE TABLE IF NOT EXISTS occupancy (
    venue_id TEXT NOT NULL,
    bucket_start TEXT NOT NULL,
    samples INTEGER NOT NULL,
    sum_free REAL NOT NULL,
    sum_occupied REAL NOT NULL,
    sum_held REAL NOT NULL,
    total INTEGER NOT NULL,
    PRIMARY KEY (venue_id, bucket_start)
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    venue_id TEXT NOT NULL,
    seat_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0
);
"""


def _iso(dt: datetime) -> str:
    return to_doha(dt).isoformat()


def _dt(text: str) -> datetime:
    return to_doha(datetime.fromisoformat(text))


def bucket_start(ts: datetime, minutes: int = BUCKET_MINUTES) -> datetime:
    ts = to_doha(ts)
    floored = ts.minute - ts.minute % minutes
    return ts.replace(minute=floored, second=0, microsecond=0)


class Repository:
    def __init__(self, path: str | Path = DB_PATH) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _execute(self, sql: str, params: Iterable = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            rows = cur.fetchall()
            self._conn.commit()
            return rows

    # --- seat events ---------------------------------------------------------
    def add_seat_event(self, event: SeatEvent, synthetic: bool = False) -> None:
        self.add_seat_events([event], synthetic=synthetic)

    def add_seat_events(self, events: Iterable[SeatEvent], synthetic: bool = False) -> None:
        rows = [
            (
                _iso(e.ts),
                e.venue_id,
                e.seat_id,
                e.old_state.value if e.old_state else None,
                e.new_state.value,
                int(synthetic),
            )
            for e in events
        ]
        if not rows:
            return
        with self._lock:
            self._conn.executemany(
                "INSERT INTO seat_events (ts, venue_id, seat_id, old_state, new_state, synthetic)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()

    def seat_events(
        self,
        venue_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        include_synthetic: bool = True,
    ) -> list[SeatEvent]:
        sql = "SELECT ts, venue_id, seat_id, old_state, new_state FROM seat_events WHERE 1=1"
        params: list = []
        if venue_id:
            sql += " AND venue_id = ?"
            params.append(venue_id)
        if since:
            sql += " AND ts >= ?"
            params.append(_iso(since))
        if until:
            sql += " AND ts <= ?"
            params.append(_iso(until))
        if not include_synthetic:
            sql += " AND synthetic = 0"
        sql += " ORDER BY ts, id"
        return [
            SeatEvent(
                ts=_dt(r["ts"]),
                venue_id=r["venue_id"],
                seat_id=r["seat_id"],
                old_state=SeatState(r["old_state"]) if r["old_state"] else None,
                new_state=SeatState(r["new_state"]),
            )
            for r in self._execute(sql, params)
        ]

    def delete_synthetic_events(self, venue_id: str | None = None) -> None:
        if venue_id:
            self._execute("DELETE FROM seat_events WHERE synthetic = 1 AND venue_id = ?", [venue_id])
        else:
            self._execute("DELETE FROM seat_events WHERE synthetic = 1")

    def delete_seat_events(self, venue_id: str, seat_id: str) -> None:
        self._execute("DELETE FROM seat_events WHERE venue_id = ? AND seat_id = ?", [venue_id, seat_id])

    def save_seat_snapshots(self, snapshots: Iterable[SeatSnapshot]) -> None:
        rows = [
            (
                snapshot.venue_id,
                snapshot.seat_id,
                snapshot.state.value,
                _iso(snapshot.state_changed_at or snapshot.since),
                _iso(snapshot.updated_at),
                None if snapshot.person_detected is None else int(snapshot.person_detected),
                None if snapshot.belongings_detected is None else int(snapshot.belongings_detected),
                snapshot.confidence,
                _iso(snapshot.unattended_since) if snapshot.unattended_since else None,
                int(snapshot.manual_override),
            )
            for snapshot in snapshots
        ]
        if not rows:
            return
        with self._lock:
            self._conn.executemany(
                "INSERT INTO seat_status (venue_id, seat_id, state, state_changed_at, updated_at, "
                "person_detected, belongings_detected, confidence, unattended_since, manual_override) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(venue_id, seat_id) DO UPDATE SET state=excluded.state, "
                "state_changed_at=excluded.state_changed_at, updated_at=excluded.updated_at, "
                "person_detected=excluded.person_detected, belongings_detected=excluded.belongings_detected, "
                "confidence=excluded.confidence, unattended_since=excluded.unattended_since, "
                "manual_override=excluded.manual_override",
                rows,
            )
            self._conn.commit()

    def seat_snapshots(self, venue_id: str) -> list[SeatSnapshot]:
        return [
            SeatSnapshot(
                venue_id=row["venue_id"],
                seat_id=row["seat_id"],
                zone="",
                has_outlet=False,
                state=SeatState(row["state"]),
                since=_dt(row["state_changed_at"]),
                state_changed_at=_dt(row["state_changed_at"]),
                updated_at=_dt(row["updated_at"]),
                person_detected=None if row["person_detected"] is None else bool(row["person_detected"]),
                belongings_detected=None if row["belongings_detected"] is None else bool(row["belongings_detected"]),
                confidence=row["confidence"],
                unattended_since=_dt(row["unattended_since"]) if row["unattended_since"] else None,
                requires_staff_review=row["state"] == SeatState.REVIEW_REQUIRED.value,
                manual_override=bool(row["manual_override"]),
            )
            for row in self._execute(
                "SELECT * FROM seat_status WHERE venue_id = ? ORDER BY seat_id", [venue_id]
            )
        ]

    # --- occupancy buckets (15 minutes) ---------------------------------------
    def record_occupancy(self, venue_id: str, ts: datetime, free: int, occupied: int, held: int) -> None:
        """Add one sample of seat counts to the bucket containing `ts`."""
        total = free + occupied + held
        self._execute(
            "INSERT INTO occupancy (venue_id, bucket_start, samples, sum_free, sum_occupied, sum_held, total)"
            " VALUES (?, ?, 1, ?, ?, ?, ?)"
            " ON CONFLICT(venue_id, bucket_start) DO UPDATE SET samples = samples + 1,"
            " sum_free = sum_free + excluded.sum_free, sum_occupied = sum_occupied + excluded.sum_occupied,"
            " sum_held = sum_held + excluded.sum_held, total = excluded.total",
            [venue_id, _iso(bucket_start(ts)), free, occupied, held, total],
        )

    def occupancy_buckets(self, venue_id: str, since: datetime | None = None) -> list[dict]:
        """Average seat counts per 15-minute bucket (live data only)."""
        sql = "SELECT * FROM occupancy WHERE venue_id = ?"
        params: list = [venue_id]
        if since:
            sql += " AND bucket_start >= ?"
            params.append(_iso(bucket_start(since)))
        sql += " ORDER BY bucket_start"
        out = []
        for r in self._execute(sql, params):
            n = max(1, r["samples"])
            out.append(
                {
                    "venue_id": r["venue_id"],
                    "ts": _dt(r["bucket_start"]),
                    "free": r["sum_free"] / n,
                    "occupied": r["sum_occupied"] / n,
                    "held": r["sum_held"] / n,
                    "total": r["total"],
                }
            )
        return out

    # --- staff alerts ------------------------------------------------------
    def add_alert(self, ts: datetime, venue_id: str, seat_id: str, kind: str, message: str) -> None:
        self._execute(
            "INSERT INTO alerts (ts, venue_id, seat_id, kind, message) VALUES (?, ?, ?, ?, ?)",
            [_iso(ts), venue_id, seat_id, kind, message],
        )

    def alerts(self, venue_id: str | None = None, unresolved_only: bool = False, limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM alerts WHERE 1=1"
        params: list = []
        if venue_id:
            sql += " AND venue_id = ?"
            params.append(venue_id)
        if unresolved_only:
            sql += " AND resolved = 0"
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [
            {
                "id": r["id"],
                "ts": _dt(r["ts"]),
                "venue_id": r["venue_id"],
                "seat_id": r["seat_id"],
                "kind": r["kind"],
                "message": r["message"],
                "resolved": bool(r["resolved"]),
            }
            for r in self._execute(sql, params)
        ]

    def resolve_alerts(self, venue_id: str, seat_id: str, kind: str | None = None) -> None:
        sql = "UPDATE alerts SET resolved = 1 WHERE venue_id = ? AND seat_id = ? AND resolved = 0"
        params: list = [venue_id, seat_id]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        self._execute(sql, params)
