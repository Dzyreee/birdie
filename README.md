---
title: Birdie
emoji: 🐦
colorFrom: green
colorTo: yellow
sdk: gradio
sdk_version: 6.31.0
python_version: "3.12"
app_file: app.py
pinned: false
short_description: Camera-verified live study seats in Doha
---

# Birdie

**A bird's-eye view of every study seat in Doha before you drive there.**
Camera-verified live seat availability and booking for cafes, libraries and study spaces.

Built at the Qai x Hugging Face Hackathon 01 (Nestwork Msheireb, Doha). Full brief: [CLAUDE.md](CLAUDE.md).
Data models and public functions: [docs/CONTRACT.md](docs/CONTRACT.md).

## What it does

- **Three seat states from one small detector** (`PekingU/rtdetr_r18vd`, COCO): `FREE`, `OCCUPIED`, `HELD`
  (belongings with nobody there for longer than the hold time).
- **Live venue view**: free seats per venue and per zone (quiet, family, women's section, terrace).
- **Verified booking**: QR check-in confirmed by the camera, automatic no-show release, staff alerts for seats held by bags.
- **Availability at your arrival time** and a **focus score** (0 to 100) with its breakdown.
- **Venue dashboard**: occupancy by hour, no-show rate, minutes held by belongings, peak times.

Only Nestwork Msheireb is live. Qatar National Library, Qatar University Library and Qahwa Corner are
**simulated** venues with **synthetic** history, and are labelled as such everywhere.

## Privacy

Frames are processed in memory and discarded. They are never written to disk or logged, and people are blurred in
every frame shown on screen (annotated frames are sent to the browser as in-memory data URLs). Only seat states are
stored. No face recognition, no identification: check-in is a QR code, and the camera only confirms that the seat is
occupied.

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
  vision/           detector.py, seats.py, state.py, render.py
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
hf upload <user>/birdie . . --repo-type space --exclude ".venv/*" "data/*" ".git/*" "**/__pycache__/*"
```
