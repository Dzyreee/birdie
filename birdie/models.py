"""Data contract shared by both backend repos (CLAUDE.md section 7, docs/CONTRACT.md).

Anything that produces or consumes seat data must use these models.
All timestamps are timezone-aware datetimes (Doha time, see birdie.clock).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SeatState(str, Enum):
    UNKNOWN = "UNKNOWN"  # no recent, usable camera evidence
    FREE = "FREE"  # no person, no belongings
    OCCUPIED = "OCCUPIED"  # a person is associated with the seat
    HELD = "HELD"  # belongings remain without a person; timer is active
    REVIEW_REQUIRED = "REVIEW_REQUIRED"  # belongings remained past the grace period
    UNAVAILABLE = "UNAVAILABLE"  # staff disabled this seat


class VenueType(str, Enum):
    cafe = "cafe"
    library = "library"
    cowork = "cowork"
    study_room = "study_room"


class VenueSource(str, Enum):
    live = "live"  # camera in the room
    recorded = "recorded"  # a recorded clip played through the camera pipeline
    simulated = "simulated"  # driven by birdie.simulator, always labelled as simulated


class _Model(BaseModel):
    model_config = ConfigDict(use_enum_values=False, extra="ignore")


class Venue(_Model):
    venue_id: str
    name: str
    area: str
    type: VenueType
    lat: float
    lon: float
    zones: list[str] = Field(default_factory=list)
    source: VenueSource
    noise_db: float = 50.0
    drive_minutes: int = 0
    open_until: str | None = None
    open_late: bool = False
    amenities: list[str] = Field(default_factory=list)
    floor_plan: dict[str, Any] | None = None


class Seat(_Model):
    seat_id: str
    venue_id: str
    zone: str
    has_outlet: bool = False
    has_window: bool = False
    table_id: str | None = None
    plan_x: float | None = None
    plan_y: float | None = None
    plan_rot: float = 0.0
    # Normalised (0..1) polygon corners as (x, y), so it works at any camera resolution.
    polygon: list[tuple[float, float]] = Field(default_factory=list)

    @field_validator("polygon")
    @classmethod
    def _check_polygon(cls, value: list[tuple[float, float]]) -> list[tuple[float, float]]:
        for x, y in value:
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise ValueError("polygon coordinates must be normalised to 0..1")
        if value and len(value) < 3:
            raise ValueError("a polygon needs at least 3 corners")
        return value


class SeatSnapshot(_Model):
    venue_id: str
    seat_id: str
    zone: str
    has_outlet: bool
    state: SeatState
    since: datetime
    updated_at: datetime
    state_changed_at: datetime | None = None
    person_detected: bool | None = None
    belongings_detected: bool | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    unattended_since: datetime | None = None
    grace_period_remaining_seconds: int | None = Field(default=None, ge=0)
    requires_staff_review: bool = False
    manual_override: bool = False


class SeatEvent(_Model):
    ts: datetime
    venue_id: str
    seat_id: str
    old_state: SeatState | None
    new_state: SeatState


class Query(_Model):
    area: str | None = None
    party_size: int = Field(1, ge=1, le=20)
    needs_outlet: bool = False
    quiet: bool = False
    zone: str | None = None
    venue_type: VenueType | None = None
    arrival_minutes: int = Field(0, ge=0, le=24 * 60)


class VenueConfig(_Model):
    """What a venues/<venue_id>.json file holds: the venue plus its seats."""

    venue: Venue
    seats: list[Seat] = Field(default_factory=list)
    ignored_person_regions: list[list[tuple[float, float]]] = Field(default_factory=list)
    camera_table_regions: dict[str, list[tuple[float, float]]] = Field(default_factory=dict)
    recording_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("ignored_person_regions")
    @classmethod
    def _check_ignored_regions(cls, regions: list[list[tuple[float, float]]]):
        for region in regions:
            if len(region) < 3 or any(not (0 <= x <= 1 and 0 <= y <= 1) for x, y in region):
                raise ValueError("ignored regions need at least 3 normalised corners")
        return regions

    @field_validator("camera_table_regions")
    @classmethod
    def _check_table_regions(cls, regions: dict[str, list[tuple[float, float]]]):
        for region in regions.values():
            if len(region) < 3 or any(not (0 <= x <= 1 and 0 <= y <= 1) for x, y in region):
                raise ValueError("table regions need at least 3 normalised corners")
        return regions
