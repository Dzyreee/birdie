"""Data contract shared by both backend repos (CLAUDE.md section 7, docs/CONTRACT.md).

Anything that produces or consumes seat data must use these models.
All timestamps are timezone-aware datetimes (Doha time, see birdie.clock).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SeatState(str, Enum):
    FREE = "FREE"  # no person, no belongings
    OCCUPIED = "OCCUPIED"  # a person, or belongings left recently
    HELD = "HELD"  # belongings with no person for longer than the hold time


class VenueType(str, Enum):
    library = "library"
    cafe = "cafe"
    cowork = "cowork"
    study_room = "study_room"


class VenueSource(str, Enum):
    live = "live"  # camera in the room
    recorded = "recorded"  # a recorded clip played through the camera pipeline
    simulated = "simulated"  # driven by birdie.simulator, always labelled as simulated


class _Model(BaseModel):
    model_config = ConfigDict(use_enum_values=False, extra="ignore")


class Table(_Model):
    """A table on the floor plan, in design points on a 362-wide plan."""

    table_id: str  # a letter, for example "A"
    name: str  # for example "Table A", "Window bar"
    shape: Literal["rect", "round"] = "rect"
    x: float | None = None  # rect
    y: float | None = None
    w: float | None = None
    h: float | None = None
    cx: float | None = None  # round
    cy: float | None = None
    r: float | None = None


class Fixture(_Model):
    label: str  # for example "Books", "Counter"
    x: float
    y: float
    w: float
    h: float


class FloorPlan(_Model):
    width: float = 362
    height: float = 430  # 360 to 490
    window_top: bool = False
    tables: list[Table] = Field(default_factory=list)
    fixtures: list[Fixture] = Field(default_factory=list)


class Venue(_Model):
    venue_id: str
    name: str
    area: str
    type: VenueType
    lat: float
    lon: float
    source: VenueSource
    drive_minutes: int = 0  # approximate, from Nestwork Msheireb
    open_until: str = ""  # display text, for example "Open till 23:00"
    open_late: bool = False
    amenities: list[str] = Field(default_factory=list)  # chip labels
    zones: list[str] = Field(default_factory=list)
    floor_plan: FloorPlan | None = None
    noise_db: float = 50.0  # optional, used only by the focus score


class Seat(_Model):
    seat_id: str  # the label users see: table letter plus number, for example "A3"
    venue_id: str
    table_id: str | None = None
    zone: str = ""
    has_outlet: bool = False
    has_window: bool = False
    plan_x: float | None = None  # chair centre on the floor plan
    plan_y: float | None = None
    plan_rot: float | None = None  # degrees: 0 above the table, 180 below, -90 left, 90 right
    # Normalised (0..1) camera polygon corners as (x, y); live venue only.
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
