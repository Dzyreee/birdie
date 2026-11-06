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
- The app does not persist source frames. Hosted Space logging and retention must be checked separately. The app stores seat states and aggregate counts.

## Models (`birdie/models.py`)

| Model | Fields |
|---|---|
| `Venue` | `venue_id: str`, `name: str`, `area: str`, `type: VenueType` (`cafe`, `library`, `cowork`), `lat: float`, `lon: float`, `zones: list[str]`, `source: VenueSource` (`live`, `recorded`, `simulated`), `noise_db: float` |
| `Seat` | `seat_id: str`, `venue_id: str`, `zone: str`, `has_outlet: bool`, `polygon: list[tuple[float, float]]` (normalised) |
| `SeatSnapshot` | `venue_id`, `seat_id`, `zone`, `has_outlet`, `state: SeatState` (`UNKNOWN`, `FREE`, `OCCUPIED`, `HELD`), `since: datetime`, `updated_at: datetime` |
| `SeatEvent` | `ts: datetime`, `venue_id`, `seat_id`, `old_state: SeatState \| None`, `new_state: SeatState` |
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
| `record_occupancy(venue_id, ts, free, occupied, held)`, `occupancy_buckets(venue_id, since=None)` | Live occupancy in 15-minute buckets |
| `add_alert(...)`, `alerts(venue_id=None, unresolved_only=False)`, `resolve_alerts(venue_id, seat_id, kind=None)` | Staff alerts |

## Venues (`birdie/venues.py`)

`load_all() -> dict[str, VenueConfig]`, `load_venue(venue_id)`, `save_venue(config)`, `zone_label(zone)`.

## Vision (`birdie/vision/`)

| Function | Purpose |
|---|---|
| `detector.detect(frame, threshold=0.4) -> list[{label, score, box}]` | RT-DETR r18 (`PekingU/rtdetr_r18vd`). Keeps COCO classes `chair`, `person`, `backpack, handbag, suitcase, laptop, cup, bottle, book, cell phone`. `box = [x1, y1, x2, y2]` in pixels of the frame passed in. Resizes to long side <= 640 internally |
| `detector.resize_long_side(frame, 640) -> PIL.Image`, `detector.load()` | Helpers. `_infer` is the pure (frame in, detections out) function wrapped with `@spaces.GPU` when `spaces` is importable |
| `seats.assign_detections(detections, seats, (w, h), min_overlap=0.2) -> {seat_id: [det]}` | Box centre inside polygon, else largest overlap above 20% |
| `seats.observe(assigned) -> {seat_id: Observation}` | `PERSON`, `ITEMS` or `EMPTY`; missing seat observations are treated as `UNKNOWN` by the tracker |
| `state.SeatStateMachine(venue_id, seat_id, clock, k=3, hold_seconds=...)` | `.update(obs) -> SeatEvent \| None`, `.tick()`, `.snapshot(seat)` |
| `state.VenueTracker(venue_id, seats, clock, on_event)` | `.process({seat_id: Observation}) -> [SeatEvent]` (missing seats = UNKNOWN), `.tick()` (hold timers and stale-feed expiry), `.snapshots()`, `.counts()`, `.force(states)`, `.set_seats(seats)` |
| `render.annotate(frame, detections)` | RGB frame with detector boxes only; no static seat regions and no blurring |
| `render.to_data_uri(frame)` | In-memory JPEG data URL (frames never touch disk) |
| `clip.iter_clip_frames(path, fps=1)` | Sample a recorded clip at 1 fps, in memory |

## Forecast (`birdie/forecast/`)

| Function | Purpose |
|---|---|
| `calendar.is_weekend(dt)` (Friday + Saturday), `day_type(dt)` (`weekday`/`friday`/`saturday`), `is_friday_prayer_quiet(dt)`, `is_ramadan(dt)`, `is_exam_season(dt)`, `is_terrace_season(dt)`, `slot_of(dt)`, `features(dt)` | Qatar calendar. `RAMADAN_RANGES`, `EXAM_RANGES` are editable |
| `synthetic.profile(venue_type, ts)`, `synthetic.generate_history(venue, n_seats, end, weeks=4) -> [{ts, occupied, free, total, synthetic}]` | Synthetic history, always labelled synthetic |
| `model.BaselineForecaster(venue_type).fit(history).predict_ratio(ts)` | Default forecaster (occupancy ratio 0..1) |
| `model.ChronosForecaster().predict(contexts, steps)`, `model.load_chronos()` | Optional `amazon/chronos-bolt-small`; raises `ForecasterUnavailable` / returns None if it can't load |
| `model.ForecastEngine(configs, clock, repo).ratio_at(venue_id, ts)` | What the app uses (`BIRDIE_USE_CHRONOS=1` to try Chronos) |

## Decision (`birdie/decision.py`)

Functions take a `LiveData` object: anything with `now()`, `venues()`, `venue(id)`, `seats(id)`, `snapshots(id)`,
and `forecast_ratio(id, ts)`. `BirdieService` implements it.

| Function | Purpose |
|---|---|
| `availability_at(data, venue_id, arrival_minutes) -> Availability` | `expected_free`, `low`, `high`, `live_free`, `forecast_free`, `live_weight`; `.summary()` |
| `blend_availability(...)` | The pure blending rule (live weight `0.5 ** (arrival / 20 min)`) |
| `focus_score(data, venue_id, arrival_minutes) -> FocusScore` | `score` 0..100 and `parts` (free 40, noise 25, outlets 20, trend 15) |
| `recommend(data, query, top=3) -> [Recommendation]` | Filters by the `Query`, ranks by focus score; each has `reasons` |

## Simulator (`birdie/simulator.py`)

`Simulator(configs, trackers, ratio_at, clock)`: `.step()` feeds observations to each simulated venue's
`VenueTracker.process` (the camera's code path); `.backfill(repo, venue_id, hours=24)` writes a synthetic event log.

## Analytics (`birdie/analytics.py`)

`venue_dashboard(repo, venue_id, seat_ids, now, hours=24, observed_since=None) -> Dashboard` with
`occupancy_by_hour`, `peak_hours`, `held_minutes_total`, `held_minutes_by_seat`. Building blocks: `seat_intervals`,
`occupancy_by_hour`, `held_minutes`.

## Service (`birdie/service.py`)

`BirdieService(repo=None, clock=None, venues=None, timers=TIMERS, detector=None)` is the one object the UI talks to:
`process_frame(venue_id, frame)`, `snapshots(venue_id)`, `zone_counts(venue_id)`, `upsert_seat(seat)`,
`delete_seat(venue_id, seat_id)`, `availability_at(venue_id, minutes)`,
`forecast` (ForecastEngine), `simulator`, `tick()`, `start()` (back-fill + 2 s scheduler), `stop()`.

## Mapping a second repo onto this contract

1. Convert your seat and venue objects to the models above (`Model.model_validate(dict)`).
2. Anything that observes seats should end in `VenueTracker.process({seat_id: Observation})`, so smoothing,
   hold timers and SeatEvents stay identical.
3. Anything that reads availability should go through `LiveData` + `birdie.decision`.
