"""Read-only JSON API for the mobile app (CLAUDE.md section 7.2). The only module that imports FastAPI.

GET /api/venues               venues (no floor plan) with seat counts
GET /api/venues/{venue_id}    one venue with its floor plan and every seat's live status

Shapes match web/mock.js exactly, plus `camera_online` (true/false for the live venue, null for
simulated ones). Status mapping: FREE -> free, OCCUPIED -> taken, HELD -> held.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from birdie.models import SeatState
from birdie.service import BirdieService

STATUS = {SeatState.FREE: "free", SeatState.OCCUPIED: "taken", SeatState.HELD: "held"}
SUMMARY_FIELDS = ("venue_id", "name", "area", "type", "lat", "lon", "source", "drive_minutes", "open_until",
                  "open_late", "amenities", "zones")
NO_STORE = {"Cache-Control": "no-store"}


def iso(dt: datetime) -> str:
    """ISO 8601 with a timezone, for example 2026-11-06T20:15:00+03:00."""
    return dt.isoformat(timespec="seconds")


def venue_summary(svc: BirdieService, venue_id: str) -> dict:
    venue = svc.venue(venue_id).model_dump(mode="json")
    out = {k: venue[k] for k in SUMMARY_FIELDS}
    counts = {"free": 0, "taken": 0, "held": 0, "total": 0}
    for snap in svc.snapshots(venue_id):
        counts[STATUS[snap.state]] += 1
        counts["total"] += 1
    out["counts"] = counts
    out["camera_online"] = svc.camera_online(venue_id)
    return out


def venue_detail(svc: BirdieService, venue_id: str) -> dict:
    out = venue_summary(svc, venue_id)
    plan = svc.venue(venue_id).floor_plan
    out["floor_plan"] = plan.model_dump(mode="json", exclude_none=True) if plan else None
    snaps = svc.snapshot_map(venue_id)
    seats = []
    for seat in svc.seats(venue_id):
        snap = snaps.get(seat.seat_id)
        if snap is None:
            continue
        seats.append({
            "seat_id": seat.seat_id,
            "table_id": seat.table_id,
            "has_outlet": seat.has_outlet,
            "has_window": seat.has_window,
            "plan_x": seat.plan_x,
            "plan_y": seat.plan_y,
            "plan_rot": seat.plan_rot,
            "status": STATUS[snap.state],
            "since": iso(snap.since),
        })
    out["seats"] = seats
    return out


def create_app(svc: BirdieService) -> FastAPI:
    """The FastAPI app with the API routes. Mount the operator console and then the web app on it."""
    app = FastAPI(title="Birdie API", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

    @app.get("/api/venues")
    def list_venues() -> JSONResponse:
        return JSONResponse([venue_summary(svc, v.venue_id) for v in svc.venues()], headers=NO_STORE)

    @app.get("/api/venues/{venue_id}")
    def get_venue(venue_id: str) -> JSONResponse:
        if venue_id not in svc.configs:
            raise HTTPException(status_code=404, detail="Venue not found")
        return JSONResponse(venue_detail(svc, venue_id), headers=NO_STORE)

    @app.get("/operator", include_in_schema=False)
    def operator_slash() -> RedirectResponse:
        return RedirectResponse(url="/operator/")

    return app


def mount_web(app: FastAPI, web_dir: str | Path) -> None:
    """Serve the mobile web app (web/) at /. Call this last: it catches every path not matched before it."""
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
