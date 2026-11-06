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
Camera-verified live seats for cafes, libraries and study spaces: see which seats are free, taken or held by a bag
before you leave home. Built at the Qai x Hugging Face Hackathon 01 (Nestwork Msheireb, Doha).
Data models, API and public functions: [docs/CONTRACT.md](docs/CONTRACT.md).

## What runs on this Space

One Docker Space, one Python process on port 7860:

| Path | What |
|---|---|
| `/` | The mobile web app (`web/`): browse Doha venues, live floor plans, Free / Taken / Held |
| `/api/venues`, `/api/venues/{id}` | Read-only JSON API the app polls every 2 seconds |
| `/operator` | Gradio operator console: Camera (clip playback, seat setup, seat status, staff alerts) and Venue dashboard |

- **One detector**, `PekingU/rtdetr_r18vd` (COCO, Apache-2.0), finds every chair, person and belonging in one pass on CPU.
- **One seat per chair.** "Detect chairs" in the console turns each detected chair into its own seat outline, matched to
  a seat id on the venue's floor plan (A3). Each frame, people and belongings are assigned to those outlines; 3-frame
  smoothing and a hold timer give `FREE`, `OCCUPIED` (Taken) or `HELD` (belongings with nobody there, 30 s in demo mode).
- **Camera input:** a clip recorded in the venue, played through the pipeline at 1 frame per second in real time
  (optionally looped). If no frame arrives for 10 s, the venue is shown as camera offline and its seats keep their state.
- **Only Nestwork Msheireb is live.** The other six venues are **simulated** with **synthetic** history and labelled
  "Simulated" everywhere.

## Privacy

Frames are processed in memory and discarded: never written to disk or logged. People are blurred (pixelated) in every
frame shown, including the operator console. The uploaded clip is deleted from the Space when playback stops. Only
seat states and counts are stored. No face recognition, no accounts, nothing about who sits where.

## Run locally

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt --index-strategy unsafe-best-match
.venv/bin/python app.py            # app at http://127.0.0.1:7860, console at /operator
.venv/bin/python -m pytest -q
```

Environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `BIRDIE_DEMO_MODE` | `1` | Demo timers (30 s hold). `0` for production timers |
| `BIRDIE_OPERATOR_PIN` | unset | If set, the Camera tab needs this PIN to play clips or change seat outlines |
| `BIRDIE_ENABLE_WEBCAM` | `0` | Show the old live-webcam input in the Camera tab |
| `BIRDIE_DB_PATH` | `data/birdie.db` | SQLite file (gitignored) |
| `BIRDIE_USE_CHRONOS` | `0` | Try `amazon/chronos-bolt-small` for forecasts (falls back to the baseline) |

## Layout

```
app.py              one FastAPI app: API, web/ at /, Gradio console at /operator; uvicorn on 7860
Dockerfile          the Space image (python app.py)
web/                mobile web app (HTML, CSS, JS; no build step)
birdie/             core package (only birdie/ui imports Gradio; only birdie/api.py imports FastAPI)
  api.py            read-only JSON API
  service.py        wires everything together; the one object the API and console talk to
  vision/           detector.py, chairs.py (one seat per chair), seats.py, state.py, render.py, clip.py
  alerts.py         staff alerts for seats held too long
  simulator.py      drives the simulated venues through the same state code
  analytics.py      dashboard numbers from the event log
  forecast/, decision.py   calendar-aware forecast, availability at arrival, focus score (not used by the app)
  evaluation.py     seat-state accuracy maths
  ui/               Gradio operator console
venues/             the 7 venues: info, floor plan, seats (plan position, camera polygon for the live venue)
tools/              extract_frames.py, label_app.py (accuracy labelling, see docs/LABELLING.md)
jobs/               backtest.py, evaluate.py (local or HF Jobs)
scripts/            deploy_space.sh, generate_venues.py, eval dataset and job helpers
tests/
```

## Deploy

```bash
scripts/deploy_space.sh affaad/birdie    # uploads only committed files with `hf upload`; Docker SDK
```

The Space runs on CPU Upgrade (Hugging Face refused free CPU for this Space type with a 402), about $0.03 an hour.

Forecast backtest as an HF Job (results pushed to a Hub dataset):

```bash
hf jobs uv run --flavor cpu-basic --secrets HF_TOKEN jobs/backtest.py --push-to <owner>/birdie-results
```
