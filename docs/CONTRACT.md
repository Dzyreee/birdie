# Birdie data contract and API

The models live in `birdie/models.py` (CLAUDE.md section 7). The mobile app (`web/`) and the backend both build
against this file. Private helpers (leading underscore) are free to change.

Rules:

- Only `birdie/api.py` imports FastAPI. Only `app.py` and `birdie/ui/` import Gradio. The mobile app lives only in `web/`.
- Every timestamp is a timezone-aware `datetime` in Doha time (UTC+3, `birdie.clock.DOHA_TZ`).
- Everything time-based takes a `clock` (`RealClock` in the app, `FakeClock` in tests). Nothing sleeps in tests.
- Timers come from `birdie.config.TIMERS` (demo or production, behind `DEMO_MODE`).
- No images are ever stored: only seat states, events and counts. People are blurred in every frame shown.

## Models (`birdie/models.py`)

| Model | Fields |
|---|---|
| `Venue` | `venue_id`, `name`, `area`, `type` (`library`, `cafe`, `cowork`, `study_room`), `lat`, `lon`, `source` (`live`, `recorded`, `simulated`), `drive_minutes` (from Nestwork Msheireb), `open_until` (display text), `open_late` (bool), `amenities` (chip labels), `zones`, `floor_plan`, `noise_db` (optional, focus score only) |
| `FloorPlan` | `width` (362), `height` (360 to 490), `window_top`, `tables: list[Table]`, `fixtures: list[Fixture]` (design points on a 362-wide plan) |
| `Table` | `table_id` (a letter), `name`, `shape` (`rect` or `round`), then `x`, `y`, `w`, `h` (rect) or `cx`, `cy`, `r` (round) |
| `Fixture` | `label`, `x`, `y`, `w`, `h` |
| `Seat` | `seat_id` (table letter plus number, for example `A3`), `venue_id`, `table_id`, `zone`, `has_outlet`, `has_window`, `plan_x`, `plan_y` (chair centre on the plan), `plan_rot` (0 above the table, 180 below, -90 left, 90 right, radial around round tables), `polygon` (normalised 0..1 camera outline, live venue only). All but `seat_id` and `venue_id` are optional, so the labelling tool's `seats.json` files load too |
| `SeatSnapshot` | `venue_id`, `seat_id`, `state` (`FREE`, `OCCUPIED`, `HELD`), `since`, `updated_at` |
| `SeatEvent` | `ts`, `venue_id`, `seat_id`, `old_state`, `new_state` |
| `Query` | `area`, `party_size`, `needs_outlet`, `quiet`, `zone`, `venue_type`, `arrival_minutes` (used by `recommend()`) |
| `VenueConfig` | `venue`, `seats` (the shape of `venues/<venue_id>.json`) |

## API (`birdie/api.py`, JSON, read-only)

| Method and path | Response |
|---|---|
| `GET /api/venues` | List of venues (no floor plan): `venue_id`, `name`, `area`, `type`, `lat`, `lon`, `source`, `drive_minutes`, `open_until`, `open_late`, `amenities`, `zones`, `counts` (`free`, `taken`, `held`, `total`), `camera_online` |
| `GET /api/venues/{venue_id}` | The same fields plus `floor_plan` and `seats`: each seat has `seat_id`, `table_id`, `has_outlet`, `has_window`, `plan_x`, `plan_y`, `plan_rot`, `status` (`free`, `taken`, `held`) and `since`. 404 for an unknown venue |

- Status mapping: `FREE` is `free`, `OCCUPIED` is `taken`, `HELD` is `held`.
- `camera_online` is `true` or `false` for the live venue (false after 10 s without a frame; its seats then keep their
  last state) and `null` for simulated venues.
- Times are ISO 8601 with a timezone (`2026-11-06T20:15:00+03:00`). Responses are sent with `Cache-Control: no-store`.
- `web/mock.js` returns the same shapes (without `camera_online`); `tests/test_api.py` checks this by running it in Node.

## Vision (`birdie/vision/`)

| Function | Purpose |
|---|---|
| `detector.detect(frame, threshold)` | RT-DETR r18 (`PekingU/rtdetr_r18vd`): `chair`, `person` and the belongings `backpack, handbag, suitcase, laptop, cup, bottle, book, cell phone`. Returns `[{label, score, box}]` in pixels of the frame passed in |
| `chairs.chair_candidates(detections, (w, h))` | Each detected chair as its own seat outline (box expanded 10%, duplicates merged), left to right |
| `chairs.auto_number(candidates, seat_ids)` | Floor-plan seat ids in natural order (A2 before A10) for the candidates |
| `seats.assign_detections(dets, seats, (w, h))` | Box centre inside an outline, else largest overlap above 20% |
| `seats.observe(assigned)` | `PERSON`, `ITEMS` or `EMPTY` per seat (chairs never count) |
| `state.SeatStateMachine`, `state.VenueTracker` | 3-frame smoothing, hold timer, `FREE` / `OCCUPIED` / `HELD`, a `SeatEvent` per change. Seats missing from a frame keep their state |
| `render.annotate(frame, detections, seats, snapshots)` | People blurred, seat outlines in the seat colours, detector boxes on top |
| `clip.iter_clip_frames(path, fps=1)`, `clip.frame_at(path, seconds)` | Clip sampling, in memory |

## Service (`birdie/service.py`)

`BirdieService` is the one object the API and the console talk to:

| Function | Purpose |
|---|---|
| `process_frame(venue_id, frame)` | One camera frame: detect, assign to chair outlines, update seat states, return the annotated (blurred) frame |
| `camera_online(venue_id)` | `True` / `False` for camera venues, `None` for simulated ones |
| `set_setup_frame(venue_id, frame)`, `chair_candidates(venue_id)`, `setup_view(venue_id, points)` | "Detect chairs" snapshot, memory only |
| `set_seat_polygon(venue_id, seat_id, polygon)`, `set_seat_polygons(venue_id, {seat_id: polygon})`, `clear_seat_polygon(...)` | Save camera outlines into existing seats; floor-plan fields are never touched |
| `venues()`, `venue(id)`, `seats(id)`, `snapshots(id)`, `counts(id)`, `zone_counts(id)` | Reads |
| `availability_at(id, minutes)` | Built, not used by the app |
| `tick()`, `start()`, `stop()` | 2 s scheduler: simulator, hold timers, staff alerts, occupancy buckets |

## Other modules

- `birdie/alerts.py`: `held_too_long(snapshots, now, seconds)`, `raise_held_alerts(repo, venue_id, snapshots, now, seconds)`, `resolve_on_event(repo, event)`.
- `birdie/storage.py`: SQLite at `data/birdie.db`: seat events, occupancy buckets, staff alerts.
- `birdie/simulator.py`: drives simulated venues through `VenueTracker.process`, the camera's code path.
- `birdie/analytics.py`: `venue_dashboard(...)`: occupancy by hour, minutes held, peak times.
- `birdie/forecast/`, `birdie/decision.py`: calendar-aware forecast, `availability_at`, `focus_score`, `recommend` (built, not used by the app).
- `birdie/evaluation.py`, `tools/`, `jobs/evaluate.py`: seat-state accuracy (see `docs/LABELLING.md`).
