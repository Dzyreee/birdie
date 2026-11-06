# Birdie: Project Brief

> **How to use this file:** It lives in the repo root as `CLAUDE.md`, so every Claude Code session starts with the full context. Teammates can also paste it into any AI assistant and say: *"This is our hackathon project brief. Help me with [your part]."*

**Birdie** gives you a bird's-eye view of every study seat in Doha before you drive there: camera-verified live seats for cafes, libraries and study spaces. See which seats are free, taken or held by a bag, before you leave home.

> **Updated Fri 6 Nov, evening.** The team dropped booking, check-in, QR codes and the Fanar assistant, and adopted the mobile app design in `design/mobile/`. Birdie is now a live view: it shows seats, it doesn't reserve them. Section 16 lists what changes in the existing code.

---

## 0. Rules for AI assistants working on this project

You are helping a 4-person team at the **Qai x Hugging Face Hackathon 01**, held in person at Nestwork Msheireb, Doha. Keep these constraints in mind for every suggestion:

- **Deadline:** the live demo link must be in the submission sheet by **Saturday 7 Nov 2026, 14:00 Doha time**. Late entries can't be judged. Code freeze at **11:00**, submit by **12:00**.
- **Everything must be built during the event.**
- **It must genuinely run on Hugging Face infrastructure** (Spaces, Hub models, HF Jobs). Frontier models (GPT, Claude, etc.) only "around the edges", never as the core.
- **Compute budget:** $100 for the whole team, one shared pool, no top-ups. HF Jobs stop after 30 minutes by default, so save outputs to the Hub from inside the job.
- **Prefer small, efficient open models.** Efficiency is a judging criterion.
- **Privacy matters:** no face recognition, no storing images, no identifying individuals.
- **Simple, working code over clever code.** Working end to end beats feature-rich and broken.
- **Never commit** tokens, `.env` files, videos, frames or model weights.
- **The mobile app's screens and behaviour come from the design handoff** in `design/mobile/` (`README.md` and `prototype.html`), screens 1 to 3 only. **Its look follows the delivery apps people in Doha already use (Talabat-style)**, as built in `web/` (section 8.2). Where this file and the handoff disagree (check-in, QR codes, sample data, walk times, colours, type), this file wins.
- **No booking, no check-in, no QR codes, no LLM assistant.** All were dropped on purpose. Don't build them or suggest them.
- **Section 5 (Key decisions) is final.** If anything else in this file seems to conflict with it, section 5 wins.

---

## 1. The hackathon

**Challenge:** Build an AI system that solves a real problem in Qatar. It must be grounded in Qatar or the wider Middle East and run on Hugging Face. **Projects that aren't clearly regional are disqualified.**

**Rules (from the organizers' slides):**
1. Teams of 2 to 4.
2. Build it here: everything submitted is built during the event.
3. Runs on Hugging Face: it genuinely runs on HF infrastructure. Frontier models only around the edges.
4. Ship a live demo: links in the submission sheet by Saturday 14:00.
5. Be in the room: in person at Nestwork Msheireb, no remote participation.
6. Code with a hug: be kind, share, help other teams.

**Judging criteria:**

| # | Criterion | What judges look for |
|---|---|---|
| 1 | Impact & relevance | A real Qatar or Middle East problem, solved well |
| 2 | Use of Hugging Face | The system genuinely runs on HF infrastructure |
| 3 | Technical execution | It actually works, end to end |
| 4 | Efficiency | Smart, resourceful use of the compute budget |
| 5 | Demo & pitch | Shown clearly and compellingly |

**Support:** HF and Qai engineers are on site most of the time, plus the event channel and daily office hours. Contact: info@trustqai.com.

**About Qai (the organizer):** Qai is Qatar's national AI company, a subsidiary of the Qatar Investment Authority. Its stated focus is *trusted, people-centric AI*. Pitch angles around **trust, privacy and verified data** land well with them.

---

## 2. The problem

### Problem statement

> In Doha, checking whether a study spot has room means a drive, not a walk. Students and remote workers who can't focus at home drive to Qatar National Library or a cafe, find it full, and drive again. Booking systems and busyness estimates don't help much, because their availability is a guess: walk-ins aren't counted, no-shows block seats, and bags left on chairs make seats look taken. People need to know **whether there is actually a free seat right now**.

### Why this is a Qatar problem, not a generic one

- **A car-dependent city.** Research on Doha attributes the dominance of private cars to urban sprawl, harsh weather and limited public transport. In a walkable city you peek into the next cafe. In Doha, every wrong guess costs a drive, parking and the heat.
- **Strong demand for study space.** In November 2025, QNL extended its Quiet Study Area into the night because patrons asked for it. QNL is also the main gathering place for students from schools across Qatar during exam season.
- **Large venues, no visibility.** The QU library alone has about 1,500 study spaces, and nobody can see which floor has free ones.
- **Booking exists but runs on trust.** QNL spaces can be reserved online, and QU study rooms can be booked for up to 4 hours a day. Neither system can tell whether a booked seat is actually used.
- **Local patterns that generic tools ignore:** the Friday and Saturday weekend, quiet Friday mornings before midday prayer, Ramadan's late-night cafe rush between iftar and suhoor, exam seasons, the winter-only outdoor terrace season, and family and women's sections in many venues.

### Founder story (open the pitch with this)

One of us has personally driven to a cafe or library to study, found no seat, and wasted the trip. Pair this with the room survey data (section 13).

---

## 3. Competitors, and why we're different

| Existing option | What it does | What it can't do |
|---|---|---|
| Google Maps "popular times" | Estimates how busy a place is from phone location data | No seats, no sections, no outlets, no "held by a bag" detection |
| UTSeat (Qatar-based app, 2021) | Book a specific restaurant seat like a cinema seat; shows real-time status and a live view | Availability depends on bookings, not verified seat by seat by camera; no study focus |
| Worka, Regus apps (coworking) | Real-time desk availability and instant booking | Only inside their own coworking spaces; booking-based, not verified |
| QNL / QU booking systems | Reserve rooms or spaces online | No check-in verification, no-shows go undetected, walk-ins aren't tracked |

**Our edge, in one line:** *every other app shows what was booked; Birdie shows what's actually happening.* We deliberately take no bookings: bookings are exactly what makes the other apps wrong.

---

## 4. The solution

Birdie is a **mobile app** (a mobile web app, see section 5) where students and remote workers see live seats before they drive, plus an **operator console** for the venue. It is view-only: users look, then go. Nobody reserves or claims a seat in the app.

### Core features (must have)

1. **Three seat states from computer vision:**
   - `FREE`: no person, no belongings. Shown green, "Free".
   - `OCCUPIED`: a person is in the seat, or stepped away recently and left belongings. Shown red, "Taken".
   - `HELD`: belongings (bag, laptop, cup) on the seat or table with **no person for longer than the hold time** (30 minutes in production, 30 seconds in demo mode). Shown amber, "Held".
2. **Browse Doha venues** (design screen 2): live free-seat counts per venue, categories, search, sort, a "Free right now" rail and drive times.
3. **Live floor plan per venue** (design screen 3): every chair coloured by its live state, with an Outlet / Window filter. Tapping a free or held chair shows its details.
4. **Staff alert** when a seat has been held by belongings for too long (in the operator console).
5. **Runs on an HF Space**, with the detector from the HF Hub.

### Should have

6. **Venue dashboard** (operator console): occupancy by hour, minutes seats were held by belongings, peak times. This is why venues would install the system.
7. **Seat-state accuracy number** for the judges (section 8.4).

### Built in the backend, not in the mobile design

Availability at arrival time, the focus score, `recommend()` and the calendar-aware forecast already exist in the code (section 8.3). They are not part of the mobile app. Keep the code, but don't spend time on them until the must-haves work end to end.

### What venues get

Live occupancy without counting people by hand, alerts for seats hogged by bags, and analytics on peak times and how long seats sit held. Customers arrive knowing there's a seat instead of circling the room.

### Possible extension (mention in the pitch, don't build)

The same occupancy data can turn down the AC in empty zones. Kahramaa's Tarsheed programme says air-conditioning is about 60 to 70% of electricity use in most buildings during summer.

---

## 5. Key decisions (final)

- **Name:** Birdie.
- **View-only app.** No booking, no check-in or check-out, no QR codes, no seat codes, no "your seat". The camera alone decides each seat's state.
- **No LLM assistant.** Fanar and the Arabic/English assistant are dropped. Nothing in the app needs a GPU.
- **Languages:** Python 3.11+ for the backend. The mobile app is plain HTML, CSS and JavaScript with no build step and no framework.
- **One Space, one process.** A single Hugging Face **Docker** Space (the repo's `Dockerfile` runs `python app.py`) serves everything from one Python process on port 7860, so all live state lives in one place:
  - `/`: the **mobile web app**, static files from `web/`. This is the product users see.
  - `/api/...`: a small read-only **JSON API** (FastAPI) that the mobile app calls (section 7.2).
  - `/operator`: the **Gradio operator console** with two tabs, **Camera** (recorded-clip playback, the "Detect chairs" seat setup, seat status and staff alerts) and **Venue dashboard**. It is mounted into the FastAPI app with `gr.mount_gradio_app`, and `app.py` runs the combined app with uvicorn.
- **Mobile app:**
  - It is a mobile web app, not a native app. The handoff README's SwiftUI / React Native suggestion does not apply. It opens from a link with no install.
  - It is designed for phone width (the design frame is 402 × 874). On a laptop it shows as a centred phone-width column.
  - It polls the API every 2 seconds for live seat states.
  - It has no accounts and sends nothing about the user.
- **Code structure:**
  - All core logic lives in the `birdie/` package.
  - Only `birdie/api.py` imports FastAPI. Only `app.py` and `birdie/ui/` import Gradio.
  - The mobile app lives only in `web/`.
- **Vision: one detector only:** `PekingU/rtdetr_r18vd` (COCO classes). COCO already covers people and belongings, so one model in one pass gives both `OCCUPIED` and `HELD`. `person` means occupied. Belongings: backpack, handbag, suitcase, laptop, cup, bottle, book, cell phone. **No OWLv2 or Grounding DINO** (slow, and not needed).
- **Frame rate:** about 1 frame per second, long side resized to at most 640 px.
- **Privacy:** frames are processed in memory and discarded, never written to disk or logged. People are **blurred** in any frame shown on screen, including the operator console. Only seat states are stored.
- **Seat colours:** three, and only three. They were checked for colour-blind separation, and none of them is red, so they never clash with the maroon brand.
  - `FREE` is green `#17804F` ("Free").
  - `OCCUPIED` is charcoal `#353A42` ("Taken").
  - `HELD` is amber `#D08A1C` with diagonal stripes ("Held by a bag"). The stripes keep it distinct for colour-blind users.
  - The floor plan legend reads **Free / Taken / Held by a bag**.
  - There is no "Yours" colour.
- **Logo:** the Birdie logo (a maroon bird in a ghutra and agal; source in `design/brand/`, sizes in `web/assets/`) is the **app icon**: home screen, browser tab and `web/manifest.webmanifest`. It is not shown inside the app's screens.
- **Look:** the layout borrows familiar delivery-app patterns (coloured header with a wavy edge, pill search, category tiles with badges, outlined cards, floating tab bar).
  - Colours: Qatar maroon `#8A1538` as the brand colour (one CSS variable, `--brand`), white, cream `#F5EFE7` and charcoal `#1F2328`. The app does not use Talabat's orange, so it doesn't look like a copy.
  - Type: Rubik throughout (a Google Font with Arabic support).
- **Timers:** all timers and thresholds live in `birdie/config.py` behind `DEMO_MODE` (on by default):

  | Setting | Demo | Production |
  |---|---|---|
  | Hold timer (OCCUPIED to HELD) | 30 s | 30 min |
  | Smoothing | 3 frames | 3 frames |

- **Testability:** everything time-based takes an injectable clock, so tests never sleep.
- **No GPU.** Vision, the simulator, analytics and the forecast all run on CPU. The Space runs on **CPU Upgrade, about $0.03 an hour**: Hugging Face refused the free CPU tier for this Space type (HTTP 402, PRO needed).
- **One seat per chair.** Every chair the detector finds becomes its own seat. "Detect chairs" in the Camera tab turns each detected chair into a seat outline on the camera frame, and the operator matches it to a seat id on the floor plan.
- **Camera input:** a clip recorded in the venue, played through the pipeline at 1 frame per second in real time (with "Loop clip"). The live webcam input is kept in the code behind `BIRDIE_ENABLE_WEBCAM`, off by default. If the live venue gets no frame for 10 seconds it is "camera offline" and its seats keep their last state.
- **Venues: Doha only.**
  - One live venue (Nestwork Msheireb, camera in the room) plus simulated venues.
  - Simulated venues are **always labelled "Simulated"** in the app (on list rows and the place screen) and in the pitch.
  - Invented places get invented names.
  - None of the handoff's placeholder data ("Old Town", "Halden Library" and so on) is used.
- **Distance is drive time, never walk time:**
  - Each venue has an approximate drive time in minutes from Nestwork Msheireb, the demo location. The app shows "N min drive".
  - The location header reads "Seats near Msheireb".
  - The "Nearest" sort uses drive time.
- **Forecast:** a calendar-aware baseline, with `amazon/chronos-bolt-small` as an optional second model compared in a backtest. Both are built, and neither is used by the mobile app.
- **Deploy:** upload to the Space with `hf upload`, not `git push`.

---

## 6. Architecture

```
[Venue camera = a clip recorded in the venue, uploaded in the operator console]
        │  frames at ~1 fps (browser to Space)
        ▼
[HF Space: one Python process, port 7860]
  ├─ /             mobile web app (web/: HTML, CSS, JS)   ◄── phones poll /api every 2 s
  ├─ /api          read-only JSON API (birdie/api.py, FastAPI)
  ├─ /operator     Gradio console: Camera + seat setup, Venue dashboard
  └─ birdie/ core
       ├─ vision      RT-DETR r18 (Hub) → seat assignment → seat state machines
       ├─ alerts      staff alerts for seats held too long
       ├─ simulator   drives the simulated venues through the same code path
       ├─ analytics   dashboard numbers from the event log
       ├─ forecast, decision   built, not used by the mobile app
       └─ storage     SQLite (seat events, occupancy buckets)
        │
        ▼
[HF Hub]
  ├─ Labelled seat-state evaluation dataset (our own frames, anonymised)
  └─ Evaluation results and forecast backtests produced by HF Jobs
```

### Repo layout

```
app.py                  builds the FastAPI app: API, web/ at /, Gradio console at /operator; runs uvicorn
web/                    mobile web app: index.html, app.css, app.js (no build step)
design/mobile/          design handoff: README.md (screens and behaviour) and prototype.html
design/brand/           the Birdie logo (source image; the app icon)
birdie/
  config.py             DEMO_MODE, timers, thresholds
  models.py             pydantic data models (section 7)
  storage.py            SQLite repository
  clock.py              real and fake clocks
  vision/               detector.py, seats.py, state.py, render.py
  api.py                read-only JSON API for the mobile app (the only module that imports FastAPI)
  service.py            wires everything together; the one object the API and console talk to
  scheduler.py          background ticks: staff alerts, occupancy buckets
  simulator.py
  analytics.py
  forecast/, decision.py  built, not used by the mobile app
  ui/                   Gradio operator console (camera, seat setup, dashboard)
venues/<venue_id>.json  venue info, floor plan, seats (floor-plan position and camera polygon)
jobs/                   backtest.py, evaluate.py (run locally or as HF Jobs)
docs/CONTRACT.md        data models, API and public functions
tests/
```

### Privacy story

Frames are processed in memory and discarded immediately. No images are stored and only seat states are kept. Even the operator view blurs people. The app has no accounts and knows nothing about who is sitting where: the camera only sees that *someone* or *something* is in a seat. In production, the same model runs on a small device at the venue, so **no images ever leave the venue**. Qatar's personal data protection law (Law No. 13 of 2016, the first general data protection law in the GCC) is why this design matters.

---

## 7. Data contract and API

The models live in `birdie/models.py` and are documented in `docs/CONTRACT.md`. The frontend and backend both build against this section; anything that produces or consumes seat data must match it.

### 7.1 Models

- **Venue:** `venue_id`, `name`, `area`, `type` (library, cafe, cowork, study_room), `lat`, `lon`, `source` (live, recorded, simulated), `drive_minutes` (approximate, from Nestwork Msheireb), `open_until` (display text, for example "Open till 23:00"), `open_late` (bool, for the "Open late" sort), `amenities` (chip labels, for example "Quiet zone", "Women's section", "Outlets", "Wi-Fi"), `zones`, `floor_plan`. `noise_db` is optional and used only by the focus score.
- **FloorPlan:** `width` (362), `height` (360 to 490), `window_top` (bool), `tables`, `fixtures`. Units are design points on a 362-wide plan; the app scales to the screen.
  - **Table:** `table_id` (a letter, for example "A"), `name` (for example "Table A", "Window bar"), `shape` (rect or round), then `x`, `y`, `w`, `h` for rect or `cx`, `cy`, `r` for round.
  - **Fixture:** `label` (for example "Books", "Counter"), `x`, `y`, `w`, `h`.
  - The prototype's `LAYOUTS` and `chairsFor()` in `design/mobile/prototype.html` show how tables and chair positions fit together.
- **Seat:** `seat_id` (the label users see: table letter plus number, for example "A3"), `venue_id`, `table_id`, `zone`, `has_outlet`, `has_window`, `plan_x`, `plan_y` (chair centre on the floor plan), `plan_rot` (degrees: 0 above the table, 180 below, -90 left, 90 right, radial around round tables), `polygon` (normalised 0 to 1 camera coordinates; live venue only).
- **SeatSnapshot:** `venue_id`, `seat_id`, `state` (FREE, OCCUPIED, HELD), `since`, `updated_at`.
- **SeatEvent:** `ts`, `venue_id`, `seat_id`, `old_state`, `new_state`.

Removed: `Booking`, `Query`, `bookable`, `bookable_fraction`, `prepaid_item`, and anything to do with check-in or QR codes.

### 7.2 API (JSON, read-only)

| Method and path | Response |
|---|---|
| `GET /api/venues` | List of venues (no floor plan), each with `counts`: `free`, `taken`, `held`, `total`, and `camera_online` |
| `GET /api/venues/{venue_id}` | Venue with `floor_plan` and `seats`. Each seat has `seat_id`, `table_id`, `has_outlet`, `has_window`, `plan_x`, `plan_y`, `plan_rot`, `status` (free, taken, held) and `since` (when it entered that status), plus `camera_online` |

Status mapping: FREE is `free`, OCCUPIED is `taken`, HELD is `held`. `camera_online` is `true` or `false` for the live venue (false after 10 s without a frame; its seats keep their last state) and `null` for simulated venues; `web/mock.js` doesn't have it. Times are ISO 8601 with a timezone (for example `2026-11-06T20:15:00Z`). `web/mock.js` returns exactly these shapes; the app uses it when the server has no `/api`.

### 7.3 Demo venues

| venue_id | Name | Type | Area | Source | Drive time (approx.) |
|---|---|---|---|---|---|
| `nestwork-msheireb` | Nestwork Msheireb | Coworking | Msheireb Downtown | Live (camera in the room) | You're here |
| `qnl` | Qatar National Library | Library | Education City | Simulated | ~15 min |
| `qu-library` | Qatar University Library | Library | Qatar University | Simulated | ~25 min |
| `qahwa-corner` | Qahwa Corner (invented) | Cafe | Lusail | Simulated | ~25 min |

Optional: add 2 to 4 more simulated venues with invented names (for example a cafe in West Bay, a study-room venue) so the browse list looks full and every category has something. Hide a category if it has no venues. The Nestwork floor plan must match the real tables in the demo room, and its seat IDs must match the camera polygons.

---

## 8. Logic details

### 8.1 Seat state

- Each live venue has **one seat per chair**. Its seats are polygons on the camera frame, set once with **"Detect chairs"** in the operator console: the detector finds every chair in a frame of the clip, each chair box (expanded a little) becomes a seat outline, and the operator matches each one to a seat id from the floor plan (or "auto-number left to right"). Only the camera polygon is saved into the seat; the floor-plan fields never change. A single seat can be fixed by clicking its 4 corners.
- Each frame:
  1. Detect chairs, people and belongings (chairs only matter for setup).
  2. Assign each detection to the seat whose polygon contains the box centre; if none does, to the seat with the largest overlap above 20%.
  3. Turn it into a raw observation per seat: `PERSON`, `ITEMS` or `EMPTY`.
  4. A new observation only counts after it holds for k consecutive frames (smoothing against occlusion and bad detections).
  5. `PERSON` gives `OCCUPIED`. `ITEMS` keeps the seat `OCCUPIED` (the person stepped away) until items have been there with no person for the hold time, then `HELD`. `EMPTY` gives `FREE`.
- Every state change is stored as a `SeatEvent`.
- Simulated venues change seat states through the same state code, driven by the simulator.
- A background scheduler ticks every 2 seconds for staff alerts and occupancy buckets.

### 8.2 Mobile app screens

The app keeps the browse and place screens of `design/mobile/README.md`, laid out like the delivery apps people in Doha already use (section 5). Screens 4 to 6 (Scan to check in, Enter code, Checked in), the floating activity bar and the toast are **dropped**. `web/` is the reference; in short:

- **Splash:** "Birdie" and "Live study seats in Doha" on maroon. Tap to skip. The logo is the app icon only, not on the screens.
- **Tab bar:** a floating pill at the bottom with Explore, Saved and About. It is hidden on the place screen.
- **Explore (home):**
  - The maroon header with a wavy bottom edge reads "Seats near **Msheireb** ⌄", with a pill search below.
  - Category tiles (All, Libraries, Cafés, Coworking, Study rooms; empty categories hidden), each with a black badge showing its live free count ("24 free" or "Full"). Tap a tile to filter; tap it again for All.
  - A greeting ("Good evening, where are you studying?") and an outlined suggestion card: the place with the most free seats for the drive, with a "See seats" button.
  - The "Free right now" cards, then "All places" with the Nearest / Most seats free / Open late sort.
  - **Seat dots:** each card and list row shows one dot per seat (green free first, then amber held, then charcoal taken). There are no place photos.
  - Rows show the name, "Type, Area", "N of M free", the drive time with a car icon ("You're here" for Nestwork), and a "Live" or "Simulated" tag.
- **Saved:** places saved with the heart on the place screen. They are kept in this browser only; there are no accounts.
- **About:** how Birdie works, what the colours mean, privacy, and which places are live or simulated.
- **Place:**
  - The maroon header shows back and save (heart) buttons, the name, "Type, Area", drive time, opening hours, a "Simulated" chip where it applies, and amenity chips (including zones such as Women's section, Family section and Quiet zone). Only the live venue shows the "Live" dot.
  - Below it: "N seats free", a line such as "16 taken and 3 held by bags, out of 36.", the All seats / Outlet / Window filter, the floor plan and the legend.
  - A chair that changes state rings once, so a change in the room is easy to spot.
  - **Seat sheet:** tapping a free or held chair opens the bottom sheet. A free seat shows "Seat A3 is free", its table, and chips for window and outlet. A held seat shows "Seat A3 is held" and "Held by a bag for N min" (from `since`). Taken chairs can't be tapped.
- **Live updates:** the app polls the API every 2 seconds.

### 8.3 Built but not used by the mobile app

- **Forecast:** calendar features (Friday and Saturday weekend, quiet Friday mornings, Ramadan and exam-season flags, hour of day), four weeks of synthetic history per venue, a baseline model and optional Chronos-Bolt. `jobs/backtest.py` compares them (MAE at 15, 30 and 60 minutes) locally or as an HF Job.
- **`availability_at(venue_id, arrival_minutes)`, `focus_score()`, `recommend()`:** they blend live data with the forecast.
- If the must-haves are finished early, the cheapest way to surface this is one line on the place screen, for example "about 6 likely free when you arrive in 15 min". This is the strongest drive-time angle for the pitch. Otherwise leave it.

### 8.4 The number for the judges

Label about 150 to 300 frames from our own footage (seat → free / occupied / held) and report **seat-state accuracy**. Run the evaluation as an HF Job and push the dataset and results to the Hub. The tooling exists: `tools/extract_frames.py`, `tools/label_app.py`, `jobs/evaluate.py`, `docs/LABELLING.md`.

---

## 9. Accounts, compute and deploy

- **Space:** `affaad/birdie`, a Docker Space on the teammate's account that holds the $100 credit, on **CPU Upgrade (about $0.03 an hour)**. Hugging Face refused free CPU for Gradio and Docker Spaces without PRO (HTTP 402), so there is no free dev Space. Yacine deploys with `scripts/deploy_space.sh affaad/birdie` (`hf upload` of committed files only) using a fine-grained token scoped to that one Space. The token is never written into any file in the repo.
- **The account owner handles anything that costs money:** HF Jobs, any hardware change, and Space secrets (for example an HF token for model downloads).
- **No GPU.** The whole app runs on CPU Upgrade at about $0.03 an hour (under $1 a day). The rest of the spend is short HF Jobs (accuracy evaluation, backtest).
- **Track every dollar** for the efficiency slide.

### Efficiency story

- One detector covers people and belongings, so one model pass per frame instead of two.
- About 1 frame per second, 640 px, on CPU.
- No LLM and no GPU: the entire live app runs on one CPU Upgrade Space at about $0.03 an hour.
- The only spend is short HF Jobs for evaluation, with results saved to the Hub.

---

## 10. Team, workflow and build plan

### Team

1. **Yacine and Daffa (backend):** the core package, vision, the API, the operator console, Doha venue data and floor plans, deploy. They split the section 16 checklist between them.
2. **Omair (frontend):** the mobile web app in `web/`: Explore, Saved, About and the place screen (section 8.2), against the API in section 7.2. Starts on mock data shaped exactly like the API responses, so wiring up later is a URL change.
3. **Khalid (pitch):**
   - The pitch deck and the demo script.
   - The room survey (section 13).
   - Organizer permission for the camera in the room.
   - Compute-cost tracking.
   - The backup video.
4. **Everyone:** frame labelling for the accuracy number, when free.

### Priority

- **Must have:**
  - The 3 seat states from the live camera.
  - The mobile app: browse and the live floor plan.
  - Doha venue data.
  - The operator Camera console.
  - Deployed on an HF Space.
- **Should have:** venue dashboard, staff alerts, accuracy evaluation, splash screen.
- **Skip:** booking, check-in, QR codes, payments, user accounts and login, the LLM assistant, a native app, place photos.

### Timeline (from Friday 20:00)

| When | Goal |
|---|---|
| Fri 20:00 to 23:00 | Frontend: screens 1 to 3 on mock data. Backend: remove booking and the assistant, add the API, floor plans and Doha data; serve `web/` and `/operator` from one process |
| Fri 23:00 to 02:00 | Wire the app to the live API; deploy; test on real phones with the camera in the room; label frames |
| Fri night | **Record a backup demo video** |
| Sat 07:00 to 11:00 | Accuracy evaluation as an HF Job, polish, rehearse. **Freeze at 11:00, submit by 12:00** (hard deadline 14:00) |

---

## 11. Demo script (about 2 minutes, live in the room)

1. **Hook (15 s):** the founder story: drove to study, no seat, wasted trip.
2. **Data (15 s):** room survey result (section 13), plus the car-dependent Doha framing.
3. **Live (60 s):** a phone mirrored on the screen, and the operator console on a laptop. **The Nestwork feed is a clip recorded at these tables in this room** (organizer permission needed), played through the pipeline at 1 frame per second in real time, looped. Say so: the detection, seat states and timers are live; the footage is recorded.
   - Open Birdie: Doha venues with drive times, Nestwork live, the others marked Simulated.
   - Open Nestwork: the floor plan matches the tables in this room, one seat per chair.
   - In the clip, a teammate stands up and leaves → the chair turns green on the phone.
   - A teammate sits down → it turns taken.
   - A bag is left on a chair with nobody there → after the demo timer it turns amber, Held. Tapping it shows "held by a bag", and a staff alert appears in the console.
   - Back on Browse, Nestwork's free count has changed with the room.
4. **Venue dashboard (15 s):** occupancy by hour, held-seat minutes, peak times.
5. **Trust and efficiency (15 s):** one small model on a CPU Space at about $0.03 an hour, total dollars spent, accuracy on our labelled set, "no images ever leave the venue."

Always keep the **backup video** ready in case the Wi-Fi or camera fails.

---

## 12. Likely judge questions, with answers

- **"Isn't this just Google popular times?"** Google estimates relative busyness from phone location. We show actual seats, outlets, windows, sections and seats held by bags, verified by camera.
- **"Why no booking? UTSeat and coworking apps do booking."** On purpose. Booking-based availability is what makes those apps wrong: walk-ins aren't counted and no-shows block seats. We show what the camera sees.
- **"Can't someone grab the seat before I get there?"** Yes, and that's honest: we show what's free right now, with a free count per venue. In a big venue like QNL, a place with 30 free seats will still have seats when you arrive.
- **"Why would a cafe or library give you camera access?"** Many venues already have cameras. Only seat states leave the device. The venue gets live occupancy, alerts for seats hogged by bags, and peak-time analytics. Libraries (QNL, QU) are natural anchor customers.
- **"Privacy?"** No face recognition, no stored images, no identifying individuals, people blurred on screen. The app has no accounts and collects nothing about its users. Designed with Qatar's data protection law in mind.
- **"Why is this Qatar-specific?"** Car-dependent sprawl and heat make every wasted check a drive, which is why we show drive times. Doha venues, family and women's sections, the Friday and Saturday weekend, Ramadan nights and exam season around QNL.
- **"Where is Hugging Face in this?"** The detector from the Hub, the whole app on a Space, evaluation and backtests on HF Jobs, the labelled dataset published to the Hub.
- **"Why only one vision model?"** COCO already includes people, bags, laptops and cups, so one small detector does both jobs in one pass. That halves the compute and lets vision run on CPU.
- **"Why a web app and not a native app?"** You open it from a link with no install, on any phone.
- **"How accurate is it?"** Report seat-state accuracy on our labelled frames, and be upfront about failure cases (occlusion, lighting).
- **"Is the other venues' data real?"** No: only Nestwork is live. The others are simulated and labelled as such, to show how Birdie works across a city.

---

## 13. Validation to collect at the event (cheap, high impact)

Ask about 20 people in the room:
1. "In the last month, have you gone to a cafe or QNL to study and found no seat?"
2. "Roughly how much time did that cost you?"
3. "Would you check an app like this before driving somewhere to study?"

Put the real numbers on a slide: for example, "X of 20 builders here said yes, losing about Y minutes each time." **Don't invent these numbers. Only use what you actually collect.**

---

## 14. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Judges call it "not clearly regional" | Lead with the Doha framing: car dependency and drive times, QNL, Doha venues, sections, Ramadan and weekend patterns |
| Judges call it a convenience app | Room survey data + venue-side value (held-seat alerts, utilisation) + verified-availability framing |
| Detection flicker from occlusion or lighting | Smoothing over k frames; good camera angle; test in the actual demo room early |
| Frontend and backend don't fit together | The API shapes in section 7.2 are fixed; the frontend builds on mock data in exactly that shape |
| Space latency or Wi-Fi failure in the demo | About 1 fps, 2 s polling; local fallback; backup video |
| Privacy concerns from the audience | No faces, no storage, blurred view, no accounts, on-device in production |
| Burning the $100 credits | One CPU Upgrade Space (about $0.03 an hour) with a sleep time; money otherwise only for short HF Jobs; track spend |

---

## 15. Sources

- Doha car dependency: [The Impact of Rapid Motorization and Urban Growth: Doha (Qatar University)](https://qspace.qu.edu.qa:8443/xmlui/handle/10576/64758) · [Public transport and thermal perception in Doha](https://qu.academia.edu/DeemaAlattar)
- QNL Night Study Space added after patron requests: [The Peninsula, Nov 2025](https://thepeninsulaqatar.com/article/09/11/2025/qatar-national-library-launches-night-study-space-for-late-night-learners)
- QNL as the exam-season hub: [Marhaba](https://marhaba.qa/?p=350213)
- QNL spaces reservable online: [Marhaba education guide](https://issuu.com/marhabaqatar/docs/marhaba_87_education_eguide/s/29064487)
- QU library has about 1,500 study spaces: [Gulf Times](https://www.gulf-times.com/story/37285/qatar-university-inaugurates-new-library)
- QU study room booking rules: [QU Library](https://www.qu.edu.qa/library/about/use-of-study-rooms)
- UTSeat (Qatar seat-booking app): [The Peninsula, 2021](https://thepeninsulaqatar.com/article/16/02/2021/Qatari-firm’s-innovative-app-makes-restaurant-seat-booking-easy)
- Coworking booking apps in Doha: [Worka](https://www.worka.com/en/locations/qatar) · [Regus](https://www.regus.com/en-us/qatar/doha/coworking)
- Qatar data protection law (Law No. 13 of 2016): [Qatar Tribune](https://www.qatar-tribune.com/article/31687/FIRSTPAGE/New-law-on-personal-data-protection/amp) · [DLA Piper overview](https://www.dlapiperdataprotection.com/guide.pdf?c=QA)
- AC share of building electricity (Tarsheed): [The Peninsula, Jul 2026](https://www.thepeninsulaqatar.com/article/26/07/2026/qatar-makes-significant-progress-in-water-power-conservation-goals)
- Hugging Face CLI and login: [HF CLI guide](https://huggingface.co/docs/huggingface_hub/guides/cli)
- Qai (organizer): [Qatar Government Communications Office](https://www.gco.gov.qa/en/media-centre/top-news/qatar-launches-qai-to-power-its-global-ai-ambitions/)
- HF Jobs pricing: [HF docs](https://huggingface.co/docs/hub/jobs-pricing)

---

## 16. Changes from the previous plan (for the backend)

The code was built for the earlier plan. To match this file:

1. **Remove booking and check-in:** `birdie/booking.py`, `birdie/ui/checkin.py`, the `Booking` model, no-show release, `bookable` seats, `bookable_fraction`, prepaid drinks, QR code generation (and the `qrcode` dependency), and the check-in timers in `config.py`. Keep the scheduler for staff alerts and occupancy buckets.
2. **Remove the assistant:** delete `birdie/assistant/` and the `Query` model if nothing else needs it.
3. **New entry point:** `app.py` builds a FastAPI app that serves `web/` at `/` and the read-only API at `/api` (`birdie/api.py`), mounts the Gradio console at `/operator`, and runs uvicorn on port 7860. If the Gradio SDK Space won't run this, switch the Space to the Docker SDK.
4. **The Gradio UI becomes the operator console:** keep Camera (with seat setup) and Venue dashboard. Drop the Find a seat tab; the mobile app replaces it.
5. **Venue JSON:** add the floor plan, seat labels (`A3`), `plan_x` / `plan_y` / `plan_rot`, `has_window`, `drive_minutes`, `open_until`, `open_late`, `amenities` and the `study_room` type. Make the Nestwork plan match the real room.
6. **Dashboard:** drop the no-show rate and anything else that came from bookings.
7. **Keep without changes:** vision, the simulator, forecast, `decision.py`, the backtest and evaluation jobs.
8. **Update the docs and tests:** `README.md` (the Space card still describes booking), `docs/CONTRACT.md`, the booking tests, and the architecture guards (FastAPI only in `birdie/api.py`; the `booking.py` exception for QR images goes away).
