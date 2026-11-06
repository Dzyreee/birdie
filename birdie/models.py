"""Data contract shared by both backend repos (CLAUDE.md section 7, docs/CONTRACT.md).

Anything that produces or consumes seat data must use these models.
All timestamps are timezone-aware datetimes (Doha time, see birdie.clock).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SeatState(str, Enum):
    FREE = "FREE"  # no person, no belongings
    OCCUPIED = "OCCUPIED"  # a person, or belongings left recently
    HELD = "HELD"  # belongings with no person for longer than the hold time


class VenueType(str, Enum):
    cafe = "cafe"
    library = "library"
    cowork = "cowork"


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


class Seat(_Model):
    seat_id: str
    venue_id: str
    zone: str
    has_outlet: bool = False
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
