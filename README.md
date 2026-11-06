---
title: Birdie
emoji: 🐦
colorFrom: green
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
short_description: Recorded study-seat availability demo
---

# Birdie

**A bird's-eye view of study-seat availability.**
The current Nestwork entry is a recorded-video demo, not a live venue feed.

Built at the Qai x Hugging Face Hackathon 01 (Nestwork Msheireb, Doha).
Data models and public functions: [docs/CONTRACT.md](docs/CONTRACT.md).

## What it does

- **Seat states** using the COCO-pretrained `PekingU/rtdetr_r18vd` detector: `FREE`, `OCCUPIED`, `HELD`,
  `REVIEW_REQUIRED`, `UNKNOWN`, and staff-set `UNAVAILABLE`. Only `FREE` seats count as available.
- **Venue view**: predicted free-seat counts and each configured seat's status.
- **Experimental availability at arrival** and a **focus score** in the operator tools; neither is validated forecasting.
- **Venue dashboard**: occupancy by hour, minutes held by belongings, peak times.

The Camera tab runs uploaded clips through detection, camera-seat association, temporal smoothing, and the state
machine. Repeat a clip to observe the accelerated 30-second belongings timer. The calibration editor uses one frame
in memory and saves only normalized camera polygons; those polygons are hidden in the normal preview and separate
from any customer floor map. Nestwork is configured as a **recorded-clip** venue, not a live camera feed.
The mobile app under `web/` is served at `/` and reads the read-only API at `/api/venues`. Qatar National Library,
Qatar University Library and Qahwa Corner remain **simulated** venues with **synthetic** history, and are labelled as such.

## Privacy

Uploaded video is processed in memory by the backend and shown without blurring. The uploaded file is deleted after
playback, but remains in temporary Space storage while processing. The calibration frame stays in process memory;
only seat polygons, state timestamps, alerts, and aggregate counts are persisted. Hugging Face logging and retention
are not verified. No face recognition or identity matching is used.

## Test the video-to-availability path

1. Run the recorded demo using `BIRDIE_DEMO_VIDEO`, as shown below. The app loops the clip in the background.
2. Open the customer app at `/`. Seat markers and counts update through the API and are labelled **Recorded**.
3. For manual inspection, run without `BIRDIE_DEMO_VIDEO`, open `/operator/`, and upload the calibrated clip in **Camera**.
   Use **Calibrate seats for this camera view** to inspect or update camera regions, then test the video.

The supplied clips are only a few seconds long and show people at several seats. Repeating them tests the pipeline and
timer mechanics, but cannot establish detection accuracy or prove the real 30-minute rule. Seat polygons must be
checked against the venue camera view before treating counts as real availability.

The first supplied clip has a provisional seven-seat camera mapping and a separate approximate schematic. Four
additional starter IDs have no camera region and stay **Checking**. The mirror is excluded from person detections.
The clips were handheld: the second clip uses a different view and is rejected until it has a separate calibration.
The recording hash binds the current mirror region and polygons to the first clip; the hash is not model training data.

## Run tests locally

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

The full app's Torch dependencies target the Linux Docker Space. Build and run that image to test model inference
locally; the lightweight test environment does not download model weights:

```bash
docker build -t birdie .
docker run --rm -p 7860:7860 birdie
```

To run the supplied first clip automatically on this Mac (stop the old container first):

```bash
docker run --rm -p 7860:7860 \
  -e BIRDIE_DEMO_VIDEO=/demo/clip.mp4 \
  -v "/path/to/the-first-clip.mp4:/demo/clip.mp4:ro" \
  -v "$(pwd)/venues:/home/user/app/venues" \
  birdie
```

Videos are excluded from the image and Git. The Space can mount a private dataset read-only at `/demo` and set
`BIRDIE_DEMO_VIDEO=/demo/clip.mp4`; the customer app receives seat states, not the recording.

Environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `BIRDIE_DEMO_MODE` | `1` | Demo timers (30 s hold). `0` for production timers |
| `BIRDIE_DEMO_VIDEO` | unset | Absolute path to the first calibrated recording; replay it automatically |
| `BIRDIE_DEMO_VENUE` | `nestwork-msheireb` | Recorded venue whose seats the demo updates |
| `BIRDIE_DB_PATH` | `data/birdie.db` | SQLite file (gitignored) |
| `BIRDIE_USE_CHRONOS` | `0` | Try `amazon/chronos-bolt-small` for forecasts (falls back to the baseline) |

## Layout

```
app.py              Gradio entry point (UI only)
birdie/             framework-free core (never imports Gradio)
  config.py         DEMO_MODE, timers, thresholds
  models.py         pydantic data contract
  storage.py        SQLite repository
  clock.py          real and fake clocks
  vision/           detector.py, seats.py, state.py (UNKNOWN and stale-feed handling), render.py
  forecast/         calendar.py, synthetic.py, model.py
  decision.py       availability_at, focus_score, recommend
  simulator.py      drives simulated venues through the same code path
  analytics.py      dashboard numbers from the event log
  service.py        wires everything together; the one object the UI talks to
  assistant/        Fanar assistant (stub)
  ui/               Gradio tab builders
venues/             venue info and seat polygons
jobs/backtest.py    forecast backtest (local or HF Job)
scripts/            venue generator
tests/
```

## Deploy

```bash
scripts/deploy_space.sh Affaad/birdiee               # deploys this repo to the Docker Space
```

The deploy script includes tracked working-tree edits and explicitly listed integration files, but not videos, model
weights, or local credentials. It checks the Space's current revision before uploading. The Docker Space listens on 7860.

Forecast backtest as an HF Job (results pushed to a Hub dataset):

```bash
hf jobs uv run --flavor cpu-basic --secrets HF_TOKEN jobs/backtest.py --push-to <owner>/birdie-results
```
