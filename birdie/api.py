"""Read-only mobile availability API and protected venue maintenance route."""

from __future__ import annotations

import os
import secrets

from fastapi import FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from birdie.config import DETECTOR_MODEL_ID, ROOT_DIR
from birdie.models import SeatSnapshot, SeatState
from birdie.service import BirdieService
from birdie.vision import detector

WEB_DIR = ROOT_DIR / "web"


class AvailabilityOverride(BaseModel):
    unavailable: bool


def _status(state: SeatState) -> str:
    if state == SeatState.FREE:
        return "free"
    if state == SeatState.HELD:
        return "held"
    if state == SeatState.UNKNOWN:
        return "unknown"
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
        "taken": counts[SeatState.OCCUPIED] + counts[SeatState.REVIEW_REQUIRED] + counts[SeatState.UNAVAILABLE],
    }


def _venue_data(svc: BirdieService, venue_id: str, details: bool = False) -> dict:
    cfg = svc.configs[venue_id]
    venue = cfg.venue.model_dump(mode="json")
    snapshots = svc.snapshot_map(venue_id)
    venue["counts"] = _counts(list(snapshots.values()))
    if details:
        venue["seats"] = [
            {
                **seat.model_dump(mode="json", exclude={"polygon"}),
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
            }
            for seat in cfg.seats
        ]
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

    return app


def mount_mobile_web(app: FastAPI) -> None:
    """Mount after API and Gradio routes so / remains the mobile app fallback."""
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
