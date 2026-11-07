"""Data contract shared by both backend repos (CLAUDE.md section 7, docs/CONTRACT.md).

Anything that produces or consumes seat data must use these models.
All timestamps are timezone-aware datetimes (Doha time, see birdie.clock).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from shapely.geometry import Polygon


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


class TableType(str, Enum):
    shared = "shared"
    private = "private"
    single_person_desk = "single_person_desk"


class _Model(BaseModel):
    model_config = ConfigDict(use_enum_values=False, extra="ignore", populate_by_name=True)


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
    no_chair: bool = False  # a sofa or bench: can be sat on without a detected chair
    table_id: str | None = None
    plan_x: float | None = None
    plan_y: float | None = None
    plan_rot: float = 0.0
    # Camera-view seat and desk regions are normalised, independent of source resolution.
    seat_polygon: list[tuple[float, float]] = Field(default_factory=list, alias="polygon")
    workspace_polygon: list[tuple[float, float]] = Field(default_factory=list)

    @field_validator("seat_polygon", "workspace_polygon")
    @classmethod
    def _check_polygon(cls, value: list[tuple[float, float]]) -> list[tuple[float, float]]:
        for x, y in value:
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise ValueError("polygon coordinates must be normalised to 0..1")
        if value and len(value) < 3:
            raise ValueError("a polygon needs at least 3 corners")
        if value:
            polygon = Polygon(value)
            if not polygon.is_valid or polygon.area <= 0:
                raise ValueError("seat and workspace polygons must enclose a valid area")
        return value


class StudyTable(_Model):
    table_id: str
    table_type: TableType
    capacity: int = Field(ge=1)
    seat_ids: list[str] = Field(min_length=1)
    table_polygon: list[tuple[float, float]] = Field(min_length=3)
    is_shareable: bool = True
    is_available_for_studying: bool = True

    @field_validator("seat_ids")
    @classmethod
    def _unique_seats(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("table seat_ids must be unique")
        return value

    @field_validator("table_polygon")
    @classmethod
    def _normalised_table_polygon(cls, value: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if any(not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0) for x, y in value):
            raise ValueError("table polygon coordinates must be normalised to 0..1")
        polygon = Polygon(value)
        if not polygon.is_valid or polygon.area <= 0:
            raise ValueError("table polygon must enclose a valid area")
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
    tables: list[StudyTable] = Field(default_factory=list)
    unmapped_seat_ids: list[str] = Field(default_factory=list)
    ignored_person_regions: list[list[tuple[float, float]]] = Field(default_factory=list)
    camera_table_regions: dict[str, list[tuple[float, float]]] = Field(default_factory=dict)
    recording_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    # Per-clip tuning, off by default so existing venues behave exactly as before.
    stabilize_camera: bool = False  # hand-held clip: move the seat outlines with the picture (vision/motion.py)
    weak_detection_floor: float | None = Field(default=None, ge=0.05, le=0.95)  # drop people/items scored below this
    belongings_threshold: float | None = Field(default=None, ge=0.05, le=0.95)  # score from which bags and cups count

    @model_validator(mode="after")
    def _check_table_links(self):
        if len(self.unmapped_seat_ids) != len(set(self.unmapped_seat_ids)):
            raise ValueError("unmapped seat ids must be unique")
        if set(self.unmapped_seat_ids) & {seat.seat_id for seat in self.seats}:
            raise ValueError("a seat cannot be both configured and unmapped")
        if not self.tables:
            return self  # Older venue files can still be read; their seats remain unverified.
        seat_by_id = {seat.seat_id: seat for seat in self.seats}
        seat_ids = set(seat_by_id)
        table_ids = [table.table_id for table in self.tables]
        if len(table_ids) != len(set(table_ids)):
            raise ValueError("table ids must be unique")
        linked: dict[str, str] = {}
        for table in self.tables:
            if table.capacity < len(table.seat_ids):
                raise ValueError(f"{table.table_id} capacity is below its configured seat count")
            if table.table_type == TableType.single_person_desk and (table.capacity != 1 or len(table.seat_ids) != 1):
                raise ValueError("single-person desks must have one seat and capacity one")
            for seat_id in table.seat_ids:
                if seat_id not in seat_ids:
                    raise ValueError(f"{seat_id} in {table.table_id} is not a configured seat")
                if seat_id in linked:
                    raise ValueError(f"{seat_id} is linked to more than one table")
                if seat_by_id[seat_id].table_id != table.table_id:
                    raise ValueError(f"{seat_id} table_id does not match its table seat_ids")
                linked[seat_id] = table.table_id
        for seat in self.seats:
            if not seat.table_id or linked.get(seat.seat_id) != seat.table_id:
                raise ValueError(f"{seat.seat_id} table_id does not match its table seat_ids")
        return self

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
