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

**See which study seats are free in Doha before you drive there.** Birdie reads camera footage with one small vision
model and shows every chair as **Free**, **Taken** or **Held by a bag**, on a phone, per venue and per seat.

**Why Doha:** it is a car city. Checking a study spot means a drive, parking and the heat, so a wrong guess wastes a
trip. Booking systems and busyness estimates are guesses (walk-ins aren't counted, no-shows block seats, a bag on a
chair looks like a person). Birdie shows what is actually happening right now. It takes no bookings, on purpose.

## Try it in 30 seconds

- **Phone app:** open **https://affaad-birdie.hf.space/** (works on any phone, no install). Browse Doha venues with
  drive times, open one to see its floor plan, one chair per seat, coloured live.
- **Operator console (for venue staff):** **https://affaad-birdie.hf.space/operator/**. Play a recorded clip into
  Nestwork, watch seats change state, see staff alerts for bags left too long, and set up the seats with "Detect chairs".
- **JSON API:** `/api/venues` and `/api/venues/{venue_id}` (the shapes are in [docs/CONTRACT.md](docs/CONTRACT.md)).

## How it works

```
recorded clip (1 frame/s)
   -> RT-DETR r18: chairs, people, bags, laptops, cups   (one model, one pass, CPU)
   -> seat assignment: each person or belonging goes to the chair outline it sits in
   -> seat states: 3-frame smoothing + hold timer -> FREE / OCCUPIED / HELD
   -> JSON API (/api/venues)
   -> phone app (polls every 2 s)
```

- **One seat per chair.** "Detect chairs" turns every detected chair into its own seat outline, matched to a seat id on
  the venue's floor plan (A3).
- **States:** a person in the seat is *Taken*. Belongings with nobody there stay *Taken*, then become *Held* after the
  hold timer (30 s in demo mode, 30 min in production). Nothing there is *Free*.
- If no frame arrives for 10 s the venue shows as camera offline and its seats keep their last state.

## Hugging Face pieces

- **Model:** [`PekingU/rtdetr_r18vd`](https://huggingface.co/PekingU/rtdetr_r18vd) (Apache-2.0, COCO), used as is, no
  fine-tuning. It is the only model the live app runs.
- **Space:** this one, a Docker Space with the app, the API and the operator console in one Python process.
- **Jobs:** [`jobs/evaluate.py`](jobs/evaluate.py) (seat-state accuracy on our labelled frames) and
  [`jobs/backtest.py`](jobs/backtest.py) (forecast comparison) are written to run as HF Jobs on `cpu-basic`. They have
  been run locally; see "Honest limits".
- Optional, off by default: [`amazon/chronos-bolt-small`](https://huggingface.co/amazon/chronos-bolt-small) for
  forecasts (`BIRDIE_USE_CHRONOS=1`).

## Privacy

Frames are processed in memory and discarded: never written to disk or logged. People are blurred (pixelated) in every
frame shown, including the operator console. A clip uploaded to the console is deleted when playback stops. Only seat
states, events and counts are stored. No face recognition, no accounts, nothing about who sits where.

## Efficiency and cost

One small detector on CPU at 1 frame per second (long side at most 640 px), no GPU and no LLM. The Space runs on
**CPU Upgrade at about $0.03 an hour** (Hugging Face refused free CPU for this Space type).

## Honest limits

- **Only Nestwork Msheireb is "live", and it runs from a recorded clip** played through the real pipeline in real time
  (looped). The detection, seat states and timers are live; the footage is recorded.
- **The other six venues are simulated.** Their seats move through the same state code, driven by a simulator.
- **The forecast is not in the app.** It exists in the code (calendar-aware baseline, optional Chronos) but runs on
  synthetic history and has not been validated on real data.
- **Seat-state accuracy on real footage has not been measured yet.** The labelling and evaluation tools are built
  ([docs/LABELLING.md](docs/LABELLING.md)); no accuracy number is claimed here.
- A chair hidden behind a person or a table may not be detected, and a bag on the table in front of a chair can be
  missed by that chair's outline.

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
