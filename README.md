---
title: Birdie
emoji: 🐦
colorFrom: green
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
short_description: Camera-verified live study seats in Doha
---

# Birdie

**A bird's-eye view of every study seat in Doha before you drive there.**
Camera-verified live seat availability and booking for cafes, libraries and study spaces.

Built at the Qai x Hugging Face Hackathon 01 (Nestwork Msheireb, Doha).
Data models and public functions: [docs/CONTRACT.md](docs/CONTRACT.md).

## What it does

- **Four derived seat states** using the COCO-pretrained `PekingU/rtdetr_r18vd` detector: `UNKNOWN` when camera
  evidence is missing or stale, `FREE`, `OCCUPIED`, and `HELD` when belongings remain without a person.
- **Live venue view**: free seats per venue and per zone (quiet, family, women's section, terrace).
- **Verified booking**: QR check-in confirmed by the camera, automatic no-show release, staff alerts for seats held by bags.
- **Availability at your arrival time** and a **focus score** (0 to 100) with its breakdown.
- **Venue dashboard**: occupancy by hour, no-show rate, minutes held by belongings, peak times.

The detector recognizes people and belongings, not chairs. A venue's seat polygons must be calibrated once in the
Camera tab; the model then uses detections inside each configured seat area to estimate availability. Only
Nestwork Msheireb is live. Qatar National Library, Qatar University Library and Qahwa Corner are
**simulated** venues with **synthetic** history, and are labelled as such everywhere.

## Privacy

In this prototype, uploaded video is sent to the Hugging Face Space and displayed without blurring. The uploaded file
is deleted after playback, but remains in temporary Space storage while processing. The app stores seat states,
bookings and aggregate counts, not source frames in its database. Hugging Face logging and retention are not verified.
No face recognition or identity matching is used.

## Run locally

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt --index-strategy unsafe-best-match
.venv/bin/python app.py            # http://127.0.0.1:7860
.venv/bin/python -m pytest -q
```

Environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `BIRDIE_DEMO_MODE` | `1` | Demo timers (30 s hold, 60 s no-show). `0` for production timers |
| `BIRDIE_DB_PATH` | `data/birdie.db` | SQLite file (gitignored) |
| `BIRDIE_USE_CHRONOS` | `0` | Try `amazon/chronos-bolt-small` for forecasts (falls back to the baseline) |
| `BIRDIE_PUBLIC_URL` | auto | Base URL used in QR check-in links |

## Layout

```
app.py              Gradio entry point (UI only)
birdie/             framework-free core (never imports Gradio)
  config.py         DEMO_MODE, timers, thresholds
  models.py         pydantic data contract
  storage.py        SQLite repository
  clock.py          real and fake clocks
  vision/           detector.py, seats.py, state.py (UNKNOWN and stale-feed handling), render.py
  booking.py        booking lifecycle, QR codes
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

The deploy script includes tracked working-tree edits and the Docker files, but not untracked videos, model weights,
or local credentials. The Docker Space must listen on port 7860.

Forecast backtest as an HF Job (results pushed to a Hub dataset):

```bash
hf jobs uv run --flavor cpu-basic --secrets HF_TOKEN jobs/backtest.py --push-to <owner>/birdie-results
```
