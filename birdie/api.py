"""Read-only mobile availability API and protected venue maintenance route."""

from __future__ import annotations

import logging
import os
import secrets
from datetime import timedelta

from fastapi import FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from birdie.config import DETECTOR_MODEL_ID, ROOT_DIR
from birdie.decision import blend_availability
from birdie.models import SeatSnapshot, SeatState
from birdie.service import BirdieService
from birdie.vision import detector

WEB_DIR = ROOT_DIR / "web"
FORECAST_STEPS = (0, 30, 60, 90, 120, 150, 180)  # minutes ahead, for the chart on the place screen

log = logging.getLogger(__name__)


class AvailabilityOverride(BaseModel):
    unavailable: bool


def _status(state: SeatState) -> str:
    if state == SeatState.FREE:
        return "free"
    if state in (SeatState.HELD, SeatState.REVIEW_REQUIRED):
        return "held"
    if state == SeatState.UNKNOWN:
        return "checking"
    return "taken"


def _counts(snapshots: list[SeatSnapshot]) -> dict[str, int]:
    counts = {state: 0 for state in SeatState}
    for snapshot in snapshots:
        counts[snapshot.state] += 1
    return {
        "total": len(snapshots),
        "free": counts[SeatState.FREE],
        "occupied": counts[SeatState.OCCUPIED],
        "held": counts[SeatState.HELD],
        "review_required": counts[SeatState.REVIEW_REQUIRED],
        "unknown": counts[SeatState.UNKNOWN],
        "unavailable": counts[SeatState.UNAVAILABLE],
        "held_or_review": counts[SeatState.HELD] + counts[SeatState.REVIEW_REQUIRED],
        "checking": counts[SeatState.UNKNOWN],
        "taken": counts[SeatState.OCCUPIED] + counts[SeatState.UNAVAILABLE],
    }


def _forecast(svc: BirdieService, venue_id: str, live_free: int, timeline: bool = False) -> dict | None:
    """Expected free study spaces when you arrive (after the venue's drive time) and over the next 3 hours.

    Starts from the verified study spaces the app shows now and blends towards the forecast, using the same
    rule as birdie.decision.availability_at. Returns None rather than failing the venue response.
    """
    try:
        total = len(svc.snapshot_map(venue_id))
        if not total:
            return None
        now = svc.now()

        def free_at(minutes: int) -> float:
            return total * (1 - svc.forecast_ratio(venue_id, now + timedelta(minutes=minutes)))

        base = free_at(0)

        def at(minutes: int) -> dict:
            a = blend_availability(venue_id=venue_id, total=total, live_free=live_free, forecast_free_now=base,
                                   forecast_free_arrival=free_at(minutes), arrival_minutes=minutes)
            return {"minutes": minutes, "at": (now + timedelta(minutes=minutes)).isoformat(),
                    "expected_free": a.expected_int, "low": a.low, "high": a.high}

        out = {"model": svc.forecast.model_name, "arrival": at(svc.configs[venue_id].venue.drive_minutes)}
        if timeline:
            out["timeline"] = [at(m) for m in FORECAST_STEPS]
        return out
    except Exception:
        log.exception("Forecast failed for %s", venue_id)
        return None


def _venue_data(svc: BirdieService, venue_id: str, details: bool = False) -> dict:
    cfg = svc.configs[venue_id]
    venue = cfg.venue.model_dump(mode="json")
    snapshots = svc.snapshot_map(venue_id)
    study = svc.study_availability(venue_id)
    venue["counts"] = {
        **_counts(list(snapshots.values())),
        "usable_study_spaces": study["usable_study_spaces"],
        "usable_seats": study["usable_seats"],
        "unmapped_seats": len(cfg.unmapped_seat_ids),
    }
    venue["unmapped_seat_ids"] = cfg.unmapped_seat_ids
    venue["forecast"] = _forecast(svc, venue_id, study["usable_study_spaces"], timeline=details)
    if details:
        study_seats = {seat["seat_id"]: seat for seat in study["seats"]}
        venue["seats"] = [
            {
                **seat.model_dump(mode="json", exclude={"seat_polygon", "workspace_polygon"}),
                "status": _status(snapshots[seat.seat_id].state),
                "state": snapshots[seat.seat_id].state.value,
                "since": snapshots[seat.seat_id].since.isoformat(),
                "state_changed_at": (snapshots[seat.seat_id].state_changed_at or snapshots[seat.seat_id].since).isoformat(),
                "updated_at": snapshots[seat.seat_id].updated_at.isoformat(),
                "person_detected": snapshots[seat.seat_id].person_detected,
                "belongings_detected": snapshots[seat.seat_id].belongings_detected,
                "confidence": snapshots[seat.seat_id].confidence,
                "unattended_since": snapshots[seat.seat_id].unattended_since.isoformat()
                if snapshots[seat.seat_id].unattended_since else None,
                "grace_period_remaining_seconds": snapshots[seat.seat_id].grace_period_remaining_seconds,
                "requires_staff_review": snapshots[seat.seat_id].requires_staff_review,
                "manual_override": snapshots[seat.seat_id].manual_override,
                **study_seats[seat.seat_id],
            }
            for seat in cfg.seats
        ]
        venue["tables"] = study["tables"]
    return venue


def create_app(svc: BirdieService) -> FastAPI:
    app = FastAPI(title="Birdie API", version="1.0")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "model_id": DETECTOR_MODEL_ID, "model_loaded": detector.is_loaded(),
                "recorded_demo": svc.recorded_demo_status}

    @app.get("/api/venues")
    def list_venues():
        return [_venue_data(svc, venue.venue_id) for venue in svc.venues()]

    @app.get("/api/venues/{venue_id}")
    def get_venue(venue_id: str):
        if venue_id not in svc.configs:
            raise HTTPException(status_code=404, detail="Venue not found")
        return _venue_data(svc, venue_id, details=True)

    @app.put("/api/venues/{venue_id}/seats/{seat_id}/unavailable")
    def set_unavailable(
        venue_id: str,
        seat_id: str,
        request: AvailabilityOverride,
        authorization: str | None = Header(default=None),
    ):
        token = os.getenv("BIRDIE_ADMIN_TOKEN", "")
        if not token:
            raise HTTPException(status_code=503, detail="Staff controls are not configured")
        supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
        if not secrets.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="Staff authorization required")
        snapshot = svc.set_seat_unavailable(venue_id, seat_id, request.unavailable)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Seat not found")
        return {
            "venue_id": venue_id,
            "seat_id": seat_id,
            "state": snapshot.state.value,
            "requires_staff_review": snapshot.requires_staff_review,
            "manual_override": snapshot.manual_override,
        }

    @app.put("/api/venues/{venue_id}/tables/{table_id}/unavailable")
    def set_table_unavailable(
        venue_id: str,
        table_id: str,
        request: AvailabilityOverride,
        authorization: str | None = Header(default=None),
    ):
        token = os.getenv("BIRDIE_ADMIN_TOKEN", "")
        if not token:
            raise HTTPException(status_code=503, detail="Staff controls are not configured")
        supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
        if not secrets.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="Staff authorization required")
        table = svc.set_table_available_for_studying(venue_id, table_id, not request.unavailable)
        if table is None:
            raise HTTPException(status_code=404, detail="Table not found")
        return {"venue_id": venue_id, "table_id": table_id,
                "is_available_for_studying": table.is_available_for_studying}

    return app


def mount_mobile_web(app: FastAPI) -> None:
    """Mount after API and Gradio routes so / remains the mobile app fallback."""
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
