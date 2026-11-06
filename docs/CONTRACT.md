# Birdie data contract

This file is the merge contract between the two backend repos. Anything that produces or consumes seat data must use
the models below (they live in `birdie/models.py`). Map your code onto the public functions listed per module; private
helpers (leading underscore) are free to change.

Rules:

- `birdie/` never imports Gradio. UI code lives only in `app.py` and `birdie/ui/`.
- Every timestamp is a timezone-aware `datetime` in Doha time (UTC+3, `birdie.clock.DOHA_TZ`).
- Everything time-based takes a `clock` (`RealClock` in the app, `FakeClock` in tests). Nothing sleeps in tests.
- Timers and thresholds come from `birdie.config.TIMERS` (demo or production, behind `DEMO_MODE`).
- Seat polygons are normalised `(x, y)` corners in `0..1`, so they work at any camera resolution.
- No images are ever stored. Only seat states, bookings and counts.

## Models (`birdie/models.py`)

| Model | Fields |
|---|---|
| `Venue` | `venue_id: str`, `name: str`, `area: str`, `type: VenueType` (`cafe`, `library`, `cowork`), `lat: float`, `lon: float`, `zones: list[str]`, `bookable_fraction: float` (0..1), `source: VenueSource` (`live`, `recorded`, `simulated`), `noise_db: float` |
| `Seat` | `seat_id: str`, `venue_id: str`, `zone: str`, `has_outlet: bool`, `bookable: bool`, `polygon: list[tuple[float, float]]` (normalised) |
| `SeatSnapshot` | `venue_id`, `seat_id`, `zone`, `has_outlet`, `state: SeatState` (`FREE`, `OCCUPIED`, `HELD`), `since: datetime`, `updated_at: datetime` |
| `SeatEvent` | `ts: datetime`, `venue_id`, `seat_id`, `old_state: SeatState \| None`, `new_state: SeatState` |
| `Booking` | `booking_id`, `venue_id`, `seat_id`, `start_time: datetime`, `status: BookingStatus` (`BOOKED_PENDING`, `QR_SCANNED`, `CHECKED_IN`, `COMPLETED`, `NO_SHOW_RELEASED`, `CANCELLED`), `created_at: datetime`, `prepaid_item: str \| None` (cafes only, mocked) |
| `Query` | `area: str \| None`, `party_size: int`, `needs_outlet: bool`, `quiet: bool`, `zone: str \| None`, `venue_type: VenueType \| None`, `arrival_minutes: int` |
| `VenueConfig` | `venue: Venue`, `seats: list[Seat]` (the shape of `venues/<venue_id>.json`) |

Zone ids used by the demo venues: `quiet`, `open`, `group`, `family`, `women`, `terrace`, `indoor`
(labels in `birdie.venues.ZONE_LABELS`).

## Storage (`birdie/storage.py`)

SQLite at `data/birdie.db` (gitignored). `Repository(path)`; use `Repository(":memory:")` in tests.

| Function | Purpose |
|---|---|
| `add_seat_event(event, synthetic=False)`, `add_seat_events(events, synthetic=False)` | Append to the seat event log. `synthetic=True` marks back-filled history for simulated venues |
| `seat_events(venue_id=None, since=None, until=None, include_synthetic=True) -> list[SeatEvent]` | Read the event log in time order |
| `save_booking(booking)`, `get_booking(booking_id)`, `bookings(venue_id=None, statuses=None)` | Bookings |
| `add_booking_event(ts, booking, old_status, new_status)`, `status_since(booking_id, status)`, `booking_events(venue_id=None)` | Booking status log (used for the confirmation window and the no-show rate) |
| `record_occupancy(venue_id, ts, free, occupied, held)`, `occupancy_buckets(venue_id, since=None)` | Live occupancy in 15-minute buckets |
| `add_alert(...)`, `alerts(venue_id=None, unresolved_only=False)`, `resolve_alerts(venue_id, seat_id, kind=None)` | Staff alerts |

## Venues (`birdie/venues.py`)

`load_all() -> dict[str, VenueConfig]`, `load_venue(venue_id)`, `save_venue(config)`, `zone_label(zone)`.
