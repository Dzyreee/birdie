# Birdie: Project Brief

> **How to use this file:** It lives in the repo root as `CLAUDE.md`, so every Claude Code session starts with the full context. Teammates can also paste it into any AI assistant and say: *"This is our hackathon project brief. Help me with [your part]."*

**Birdie** gives you a bird's-eye view of live study seat availability in Doha before you drive there.

---

## 0. Rules for AI assistants working on this project

You are helping a 4-person team at the **Qai x Hugging Face Hackathon 01**, held in person at Nestwork Msheireb, Doha. Keep these constraints in mind for every suggestion:

- **Deadline:** the live demo link must be in the submission sheet by **Saturday 7 Nov 2026, 14:00 Doha time**. Late entries can't be judged. Code freeze at **11:00**, submit by **12:00**.
- **Everything must be built during the event.**
- **It must genuinely run on Hugging Face infrastructure** (Spaces, Hub models, HF Jobs). Frontier models (GPT, Claude, etc.) only "around the edges", never as the core.
- **Compute budget:** $100 for the whole team, one shared pool, no top-ups. HF Jobs stop after 30 minutes by default, so save outputs to the Hub from inside the job.
- **Prefer small, efficient open models.** Efficiency is a judging criterion.
- **Privacy matters:** no face recognition or identity matching; do not persist raw images, and verify hosted Space logging and retention.
- **Simple, working code over clever code.** Working end to end beats feature-rich and broken.
- **Never commit** tokens, `.env` files, videos, frames or model weights.
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

> In Doha, checking whether a study spot has room means a drive, not a walk. Students and remote workers who can't focus at home drive to Qatar National Library or a cafe, find it full, and drive again. Booking systems don't help much, because their availability is a guess: walk-ins aren't counted, no-shows block seats, and bags left on chairs make seats look taken. People need to know **whether there will actually be a seat when they arrive**.

### Why this is a Qatar problem, not a generic one

- **A car-dependent city.** Research on Doha attributes the dominance of private cars to urban sprawl, harsh weather and limited public transport. In a walkable city you peek into the next cafe. In Doha, every wrong guess costs a drive, parking and the heat.
- **Strong demand for study space.** In November 2025, QNL extended its Quiet Study Area into the night because patrons asked for it. QNL is also the main gathering place for students from schools across Qatar during exam season.
- **Large venues, no visibility.** The QU library alone has about 1,500 study spaces, and nobody can see which floor has free ones.
- **Booking exists but runs on trust.** QNL spaces can be reserved online, and QU study rooms can be booked for up to 4 hours a day. Neither system can tell whether a booked seat is actually used.
- **Local calendar patterns that generic tools ignore:** the Friday and Saturday weekend, quiet Friday mornings before midday prayer, Ramadan's late-night cafe rush between iftar and suhoor, exam seasons, and the winter-only outdoor terrace season.

### Founder story (open the pitch with this)

One of us has personally driven to a cafe or library to study, found no seat, and wasted the trip. Pair this with the room survey data (section 13).

---

## 3. Competitors, and why we're different

| Existing option | What it does | What it can't do |
|---|---|---|
| Google Maps "popular times" | Estimates how busy a place is from phone location data | No seats, no sections, no outlets or noise level, no booking, no "held by a bag" detection |
| UTSeat (Qatar-based app, 2021) | Book a specific restaurant seat like a cinema seat; shows real-time status and a live view | Availability depends on bookings, not verified seat by seat by camera; no study focus |
| Worka, Regus apps (coworking) | Real-time desk availability and instant booking | Only inside their own coworking spaces; booking-based, not verified |
| QNL / QU booking systems | Reserve rooms or spaces online | No check-in verification, no-shows go undetected, walk-ins aren't tracked |

**Our edge, in one line:** *Birdie shows observed seat availability before you drive there.*

---

## 4. The solution

### Core features (must have)

1. **Seat states from computer vision:**
   - `UNKNOWN`: no recent usable camera evidence; never offer it as free.
   - `FREE`: no person, no belongings.
   - `OCCUPIED`: a person is in the seat, or stepped away recently and left belongings.
   - `HELD`: belongings (bag, laptop, cup) on the seat or table with **no person for longer than the hold time** (30 minutes in production, 30 seconds in demo mode).
2. **Live venue view:** free seat counts per venue and per zone (quiet zone, family section, women's section, terrace, where the venue has them).
3. **Object-detection preview:** show COCO detections for chairs, people, and belongings over the original uploaded video. This preview does not draw a seat map or decide whether a chair is free.
4. **Runs on an HF Space**, with models from the HF Hub. A seat held by belongings for too long triggers a staff alert.

### Differentiators (should have)

5. **Availability at your arrival time:** "about 6 seats likely free when you arrive in 25 minutes." This matters because everyone drives. Built from live data, a forecast and Qatar calendar features.
6. **Focus score (0 to 100):** combines free seats at arrival, noise level (a decibel number only, no audio recorded), free seats with outlets and the crowd trend. Answers the real need: "I can't focus at home, where can I focus *now*?"
7. **Ask in Arabic or English:** for example, "quiet seat with outlets for two near Lusail, arriving in 20 minutes." Answered with Qatar's own Arabic LLM, Fanar (see section 8.6).
8. **Venue dashboard:** occupancy by hour, minutes seats were held by belongings, and peak times. This is why venues would install the system.

### Possible extension (mention in the pitch, don't build)

The same occupancy data can turn down the AC in empty zones. Kahramaa's Tarsheed programme says air-conditioning is about 60 to 70% of electricity use in most buildings during summer.

---

## 5. Key decisions (final)

- **Name:** Birdie.
- **Language:** Python 3.11+ for everything.
- **App:** one Gradio app (`gr.Blocks`, launched with `demo.launch()`) deployed as a single Hugging Face Space, with three tabs: **Find a seat**, **Venue dashboard**, **Camera**. All live state lives in this one process.
- **Code structure:** all core logic lives in the `birdie/` package and **never imports Gradio**. UI code lives only in `app.py` and `birdie/ui/`. This keeps the core reusable and makes merging with the second backend repo easy.
- **Vision: one detector only:** `PekingU/rtdetr_r18vd` (COCO classes). Show `chair`, `person`, backpack, handbag, suitcase, laptop, cup, bottle, book and cell phone detections. The model detects objects; it does not decide seat vacancy.
- **Frame rate:** about 1 frame per second, long side resized to at most 640 px.
- **Privacy:** the hosted Space receives camera frames for inference. The camera preview displays the original, unblurred clip. The app does not persist source frames; Space logging and retention remain to be verified.
- **Timers:** all timers and thresholds live in `birdie/config.py` behind `DEMO_MODE` (on by default):

  | Setting | Demo | Production |
  |---|---|---|
  | Hold timer (OCCUPIED to HELD) | 30 s | 30 min |
  | Smoothing | 3 frames | 3 frames |
  | Camera stale timeout | 10 s | 10 s |

- **Testability:** everything time-based takes an injectable clock, so tests never sleep.
- **Assistant:** `QCRI/Fanar-1-9B-Instruct` **without tool calling** (Fanar 1 doesn't support it). The model turns the question into a `Query` object, Python computes the answer, and the model phrases the reply. Which GPU it runs on is decided later.
- **ZeroGPU rule:** if we ever run on ZeroGPU, functions decorated with `@spaces.GPU` run in a separate worker process, so they must be pure (frame in, detections out). Seat state is never changed inside them.
- **Venues:** one live venue (Nestwork Msheireb, camera in the room) plus simulated venues. Simulated venues and synthetic history are **always labelled** as simulated or synthetic, in the UI and in the pitch.
- **Forecast:** a calendar-aware baseline by default; `amazon/chronos-bolt-small` as an optional second model, compared in a backtest.
- **Deploy:** upload to the Space with `hf upload`, not `git push`.

---

## 6. Architecture

```
[Uploaded recorded clip for object-detection preview]
        │  frames at ~1 fps (browser to Space)
        ▼
[HF Space: one Gradio app, one process]
  ├─ birdie/vision     RT-DETR r18 (Hub) → chair, person and belongings detections
  ├─ birdie/vision     configured seat association → seat state machines for availability
  ├─ birdie/forecast   Qatar calendar, synthetic history, baseline + Chronos-Bolt
  ├─ birdie/decision   availability at arrival, focus score, recommend()
  ├─ birdie/simulator  drives the simulated venues through the same code path
  ├─ birdie/analytics  dashboard numbers from the event log
  ├─ birdie/assistant  Fanar: question → Query → recommend() → reply (later)
  ├─ storage           SQLite (seat events, occupancy buckets)
  └─ UI tabs           Find a seat · Venue dashboard · Detection preview
        │
        ▼
[HF Hub]
  ├─ Labelled seat-state evaluation dataset (our own frames, anonymised)
  └─ Evaluation results and forecast backtests produced by HF Jobs
```

### Repo layout

```
app.py                  Gradio entry point (UI only)
birdie/
  config.py             DEMO_MODE, timers, thresholds
  models.py             pydantic data models (section 7)
  storage.py            SQLite repository
  clock.py              real and fake clocks
  vision/               detector.py, seats.py, state.py
  forecast/             calendar.py, synthetic.py, model.py
  decision.py
  simulator.py
  analytics.py
  assistant/            (later)
  ui/                   Gradio tab builders
venues/<venue_id>.json  venue info and seat polygons
jobs/backtest.py        forecast backtest (runs locally and as an HF Job)
docs/CONTRACT.md        data models and public functions, for merging repos
tests/
```

### Privacy story

In this hosted prototype, camera frames are sent to the Hugging Face Space for inference and processed in memory. The camera preview shows the original, unblurred clip. The app does not write source frames to its database. Space logging and retention must be verified before making a "never stored" claim or using production footage. Edge inference that keeps images on venue hardware is a future deployment option, not current behavior.

---

## 7. Data contract

Both backend repos use these models (in `birdie/models.py`, documented in `docs/CONTRACT.md`). Anything that produces or consumes seat data must match them.

- **Venue:** `venue_id`, `name`, `area`, `type` (cafe, library, cowork), `lat`, `lon`, `zones`, `source` (live, recorded, simulated), `noise_db`
- **Seat:** `seat_id`, `venue_id`, `zone`, `has_outlet`, `polygon` (normalised 0 to 1 coordinates, used internally for availability association)
- **SeatSnapshot:** `venue_id`, `seat_id`, `zone`, `has_outlet`, `state` (UNKNOWN, FREE, OCCUPIED, HELD), `since`, `updated_at`
- **SeatEvent:** `ts`, `venue_id`, `seat_id`, `old_state`, `new_state`
- **Query:** `area`, `party_size`, `needs_outlet`, `quiet`, `zone`, `venue_type`, `arrival_minutes`

### Demo venues

| venue_id | Name | Source |
|---|---|---|
| `nestwork-msheireb` | Nestwork Msheireb, Doha | Live (camera in the room) |
| `qnl` | Qatar National Library, Education City | Simulated |
| `qu-library` | Qatar University Library | Simulated |
| `qahwa-corner` | Qahwa Corner (demo cafe), Lusail | Simulated (invented name) |

---

## 8. Logic details

### 8.1 Seat state

- Availability states currently use configured seat polygons, which are not drawn in the Camera preview. The model preview only draws detector boxes.
- Each frame:
  1. Detect people and belongings.
  2. Assign each detection to the seat whose polygon contains the box centre; if none does, to the seat with the largest overlap above 20%.
  3. Turn it into a raw observation per seat: `PERSON`, `ITEMS` or `EMPTY`; if the tracker receives no observation for a seat, it uses `UNKNOWN`.
  4. A new observation only counts after it holds for k consecutive frames (smoothing against occlusion and bad detections).
  5. `PERSON` gives `OCCUPIED`. `ITEMS` keeps the seat `OCCUPIED` (the person stepped away) until items have been there with no person for the hold time, then `HELD`. `EMPTY` gives `FREE`; `UNKNOWN` is excluded from availability. A camera feed with no usable frame for 10 seconds expires all known states to `UNKNOWN`.
- Every state change is stored as a `SeatEvent`.

### 8.3 Forecast

- **Calendar features:** weekend is Friday and Saturday; Friday mornings are quiet until after midday prayer; Ramadan flag and exam-season flag (configurable date ranges); hour of day.
- **History:** live data captured during the event plus four weeks of **synthetic** history per venue in 15-minute buckets, shaped by venue type and the calendar. Clearly labelled synthetic.
- **Models:** baseline = average occupancy by venue, day type and 15-minute slot, adjusted by the calendar flags. Optional: `amazon/chronos-bolt-small`.
- **Backtest:** `jobs/backtest.py` holds out the last week and compares both models (MAE on free seats at 15, 30 and 60 minute horizons). Runs locally on CPU and as an HF Job, results pushed to the Hub.

### 8.4 Availability at arrival

`availability_at(venue_id, arrival_minutes)` blends the live free-seat count with the forecast (live data counts more for short arrival times) and returns expected free seats with a low/high range.

### 8.5 Focus score and recommendations

- `focus_score(venue_id, arrival_minutes)`, 0 to 100, with a breakdown shown to the user:
  - Free-seat ratio at arrival: 40%
  - Noise level (`noise_db`): 25%
  - Free seats with outlets: 20%
  - Crowd trend (emptying is better): 15%
- `recommend(query)` filters venues by the query (party size, outlets, quiet, zone, type, area), ranks them by focus score, and returns the top 3 with short reasons.

### 8.6 Assistant (Arabic and English)

1. Fanar reads the question and outputs a `Query` as JSON.
2. Python runs `recommend()` and `availability_at()` on live data.
3. Fanar writes the reply in the user's language.

Why not tool calling: Fanar-1-9B-Instruct doesn't support it. Fanar-2-27B-Instruct does, but at 27B it's too heavy for our budget and too risky live. Fallback if Fanar is too slow: a small Qwen instruct model.

### 8.7 The number for the judges

Label about 150 to 300 frames from our own footage (seat → free / occupied / held) and report **seat-state accuracy**. Run the evaluation as an HF Job and push the dataset and results to the Hub.

---

## 9. Accounts, compute and deploy

- **Dev Space:** `birdie` on Yacine's Hugging Face account, free CPU. Deploy with `hf upload`, excluding `.venv`, `data/` and anything gitignored.
- **Final Space:** `birdie` on the teammate's account that holds the $100 credit. Yacine pushes to it with a fine-grained token scoped to that one Space. The token is never written into any file in the repo.
- **The account owner handles anything that costs money:** switching hardware, a short sleep time so paid hardware doesn't idle, and Space secrets (for example an HF token for model downloads).
- **GPU only when needed:** vision, forecasting and decisions run on CPU. A GPU is only needed for the assistant (Fanar). Ask the HF engineers on site whether ZeroGPU is available, or which paid tier makes sense.
- **Track every dollar** (hardware hours, Jobs) for the efficiency slide.

### Efficiency story

- One detector covers people and belongings, so one model pass per frame instead of two.
- About 1 frame per second, 640 px, on CPU.
- A small forecaster (baseline, optional Chronos-Bolt small) on CPU.
- GPU only for the LLM, with a short sleep time.

---

## 10. Team, workflow and build plan

### Team

1. **Yacine (software lead):** this repo: foundation, vision, forecast, decision logic, deploy.
2. **Coding teammate:** backend work in a separate repo. The two repos get merged into a new repo, keeping the best of both, using the data contract in section 7.
3. **Two teammates (research and pitch):** organizer permission for the camera in the room, asking HF engineers about hardware, the room survey, venue clips (with permission), the pitch deck, compute-cost tracking, and frame labelling.

### Priority

- **Must have:** seat zones, 4 states including `UNKNOWN`, a tested video detector, deployed on an HF Space.
- **Should have:** availability at arrival time, focus score, venue dashboard, Arabic/English assistant.
- **Fake or skip:** payments (mocked), real cafe partnerships (simulated venues, clearly labelled), user accounts and login.

### Timeline (from Friday 17:00)

| When | Goal |
|---|---|
| Fri 17:00 to 20:00 | Foundation, vision core, detection preview; first deploy to the dev Space |
| Fri 20:00 to 23:00 | Forecast, decision logic, Find a seat and dashboard tabs; merge with the second repo |
| Fri 23:00 to 02:00 | Arabic/English assistant; move to the final Space if a GPU is needed; teammates label frames |
| Fri night | **Record a backup demo video** |
| Sat 07:00 to 11:00 | Accuracy evaluation as an HF Job, polish, rehearse. **Freeze at 11:00, submit by 12:00** (hard deadline 14:00) |

---

## 11. Demo script (about 2 minutes, live in the room)

1. **Hook (15 s):** the founder story: drove to study, no seat, wasted trip.
2. **Data (15 s):** room survey result (section 13), plus the car-dependent Doha framing.
3. **Live (60 s):**
   - Birdie shows "Nestwork Msheireb" with live seats from a laptop camera pointed at tables in this room (organizer permission needed).
   - A teammate stands up → the seat flips to `FREE`.
   - A bag is left on a chair → after the demo timer it flips to `HELD`.
   - Ask in Arabic: "Where can I study near Msheireb in 20 minutes?" → the answer gives availability at arrival and a focus score.
4. **Venue dashboard (15 s):** occupancy by hour and held-seat minutes.
5. **Trust and efficiency (15 s):** models used, total dollars spent, accuracy on our labelled set, and the actual frame-processing and retention behavior of the hosted Space.

Always keep the **backup video** ready in case the Wi-Fi or camera fails.

---

## 12. Likely judge questions, with answers

- **"Isn't this just Google popular times?"** Google estimates relative busyness from phone location. We show seat availability, sections, outlets, noise, seats held by bags, and availability when you arrive.
- **"UTSeat and coworking apps already do booking."** Birdie focuses on observed seat availability and belongings detection; it does not offer reservations.
- **"Why would a cafe or library give you camera access?"** Many venues already have cameras. In this hosted prototype, sampled frames are sent to the Space; the app database stores seat events and aggregates, not source frames. A venue deployment would need an approved retention policy, and edge inference can be evaluated if frames must stay on site.
- **"Privacy?"** No face recognition or identity matching. The camera preview shows unblurred frames sent to the hosted Space; platform logging and retention need verification before production use.
- **"Why is this Qatar-specific?"** Car-dependent sprawl and heat make every wasted check a drive. Qatar-specific calendar patterns (Ramadan nights, the Friday and Saturday weekend, exam season around QNL). Arabic-first assistant using Qatar's own LLM (Fanar).
- **"Where is Hugging Face in this?"** Models from the Hub, the app and inference on a Space, evaluation and backtests on HF Jobs, the labelled dataset published to the Hub.
- **"Why only one vision model?"** COCO already includes people, bags, laptops and cups, so one small detector does both jobs in one pass. That halves the compute and lets vision run on CPU.
- **"How accurate is it?"** Report seat-state accuracy on our labelled frames, and be upfront about failure cases (occlusion, lighting).
- **"Is the other venues' data real?"** No: only Nestwork is live. The others are simulated and labelled as such, to show how Birdie works across a city.

---

## 13. Validation to collect at the event (cheap, high impact)

Ask about 20 people in the room:
1. "In the last month, have you gone to a cafe or QNL to study and found no seat?"
2. "Roughly how much time did that cost you?"
3. "Would live, camera-verified seat counts change where or when you decide to study?"

Put the real numbers on a slide: for example, "X of 20 builders here said yes, losing about Y minutes each time." **Don't invent these numbers. Only use what you actually collect.**

---

## 14. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Judges call it "not clearly regional" | Lead with the Doha framing (car dependency, QNL, Ramadan and weekend patterns, Arabic assistant using Fanar) |
| Judges call it a convenience app | Room survey data + venue-side value (utilisation) + verified-availability framing |
| Detection flicker from occlusion or lighting | Smoothing over k frames; good camera angle; test in the actual demo room early |
| Space latency or Wi-Fi failure in the demo | About 1 fps; local fallback; backup video |
| Merging two backend repos eats the night | Both repos follow the data contract (section 7); merge module by module |
| Fanar is slow or won't fit the budget | Parse, compute, phrase pattern (no tool calling); small Qwen fallback |
| Scope grows beyond the deadline | Keep the demo focused on video detections, honest seat availability and evaluation |
| Privacy concerns from the audience | Explain hosted frame transmission accurately, verify Space retention; assess edge inference for production |
| Burning the $100 credits | CPU for everything except the LLM, short sleep time, shut down idle hardware, track spend |

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
- Fanar models: [Fanar 2.0 collection](https://huggingface.co/collections/QCRI/fanar-20) · [Fanar-2-27B-Instruct model card](https://huggingface.co/QCRI/Fanar-2-27B-Instruct) (its comparison table shows Fanar 1 has no tool calling)
- Hugging Face CLI and login: [HF CLI guide](https://huggingface.co/docs/huggingface_hub/guides/cli)
- Qai (organizer): [Qatar Government Communications Office](https://www.gco.gov.qa/en/media-centre/top-news/qatar-launches-qai-to-power-its-global-ai-ambitions/)
- HF Jobs pricing: [HF docs](https://huggingface.co/docs/hub/jobs-pricing)
