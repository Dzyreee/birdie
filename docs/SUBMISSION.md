# Submission pack

Everything here is a draft. Each claim is tied to where it comes from; anything we can't back is in
"Claims we must not make". Fill the `[ ]` placeholders yourselves.

## 1. Submission sheet

| Column | Draft |
|---|---|
| **Team name** | `[Team Birdie]` (placeholder: confirm the name the team registered with) |
| **Team members** | Yacine, Daffa, Omair, Khalid |
| **Project title** | Birdie: live study seats in Doha |
| **Problem solved (1 line)** | In car-dependent Doha, finding out a study spot is full costs a drive, so Birdie shows which seats are free, taken or held by a bag, right now, before you leave home. |
| **Space URL** | https://huggingface.co/spaces/affaad/birdie (app: https://affaad-birdie.hf.space/) |
| **Fine-tuned model URL** | *(blank: optional, we have none)* |
| **Base model** | [`PekingU/rtdetr_r18vd`](https://huggingface.co/PekingU/rtdetr_r18vd) (RT-DETR r18, COCO, Apache-2.0), used without fine-tuning |
| **How the model is used (1 sentence)** | One RT-DETR r18 pass per frame at 1 frame per second on CPU finds every chair, person and bag, and a state machine turns each chair's contents into Free, Taken or Held. |
| **Dataset URL** | *(blank: optional. We have no published dataset yet. If the labelled frames are pushed to a Hub dataset by the deadline, put its URL here.)* |
| **Demo video URL** | `[paste the link here]` |

## 2. Demo video script (about 2 minutes)

Follows section 11 of CLAUDE.md, adapted to the recorded clip. **Say clearly that the Nestwork footage is recorded.**
Record the screen of a phone showing the app, plus the operator console on a laptop. Do a dry run first: the first
page load after a restart is slower, and a clip must be re-uploaded after every restart (outlines saved in the
operator console are lost on a restart unless they are committed to `venues/nestwork-msheireb.json`).

| # | Time | Shot | Voiceover |
|---|---|---|---|
| 1 | 0:00 to 0:15 | A team member at a desk, then a car on a Doha road (or a map with drive times) | "I have driven to a library to study, found no seat, and driven home. In Doha every wrong guess costs a drive, parking and the heat. Booking apps and busyness estimates are guesses: they don't know if the seat is really free." |
| 2 | 0:15 to 0:30 | Slide with the room survey result `[X of 20 builders here said yes, losing about Y minutes each time]` | "We asked people in this room. `[numbers from the survey; delete this shot if we didn't collect them]`." |
| 3 | 0:30 to 0:45 | Phone: open https://affaad-birdie.hf.space/, splash, Explore, scroll the venues, tap the drive times | "This is Birdie. It lists Doha study places with drive times and how many seats are free right now. Only Nestwork is live; the other places are simulated to show the idea across the city." |
| 4 | 0:45 to 1:05 | Laptop: operator console, upload the recorded clip, press Play with Loop on. Phone beside it: Nestwork's floor plan | "Nestwork's feed is a clip we recorded at these tables, played through the real pipeline in real time. One small model finds every chair, person and bag. Each chair is its own seat on the floor plan. People are blurred, even here." |
| 5 | 1:05 to 1:25 | Phone: floor plan, a chair turns Taken, then Free as the person leaves/returns in the clip | "When a person leaves, the chair turns free on the phone within seconds. When someone sits down, it turns taken." |
| 6 | 1:25 to 1:45 | Clip moment with a bag left on a chair; chair turns amber after the 30 s demo timer; tap it; console shows a staff alert | "A bag with nobody there stays taken, then becomes held after the hold timer: 30 seconds in the demo, 30 minutes in production. The app says held by a bag, and the venue gets a staff alert." |
| 7 | 1:45 to 2:00 | Console: Venue dashboard (occupancy by hour, minutes held, peak times), then the closing slide | "Venues get live occupancy, alerts, and peak times. One small model on a CPU Space that costs about three cents an hour. Birdie shows what is actually happening, not what was booked." |

Do not say "no images leave the venue" in the video (see section 5). Say instead: "frames are processed in memory,
blurred on screen, and never stored."

## 3. Slide outline (7 slides)

1. **Title.** "Birdie: live study seats in Doha." Key line: *See if there's a free seat before you drive.*
2. **The problem.** Key line: *In Doha, a wrong guess is a drive.* Car-dependent city, QNL as exam-season hub, booking
   apps that can't tell if a booked seat is used (sources in CLAUDE.md section 15).
3. **Why existing tools fail.** Key line: *Every other app shows what was booked; Birdie shows what's actually
   happening.* Google popular times, UTSeat, coworking apps, QNL/QU booking (table in CLAUDE.md section 3).
4. **The product.** Key line: *Three states, one chair at a time.* Screenshots: Explore, floor plan, held-by-a-bag sheet.
   Free / Taken / Held by a bag.
5. **How it works.** Key line: *One small model, one pass, on CPU.* The diagram from the README: clip → RT-DETR r18 →
   seat assignment → state machine → API → phone. Mention Hugging Face: the model from the Hub, the Space, evaluation
   as an HF Job.
6. **Trust and efficiency.** Key line: *Frames in memory, people blurred, only seat states stored; about $0.03 an hour.*
   Total spend `[from the Hugging Face billing page]`.
7. **Honest status and what's next.** Key line: *Nestwork runs from a recorded clip; the rest is simulated.* Next:
   on-device vision at venues, real forecast (arrival-time availability), measured accuracy `[add the number only if the
   evaluation job has run]`.
8. *(Optional)* **Survey and team.** `[survey numbers, only if collected]`, the four of us.

## 4. Numbers we can honestly claim

| Claim | Where it comes from |
|---|---|
| One vision model, `PekingU/rtdetr_r18vd`, Apache-2.0, no fine-tuning | `birdie/config.py` (`DETECTOR_MODEL_ID`); licence on the model card |
| Runs on CPU, no GPU, no LLM | `birdie/vision/detector.py` picks CUDA only if present; the Space is CPU Upgrade (`hf spaces info affaad/birdie`) |
| About 1 frame per second, long side at most 640 px | `birdie/config.py` (`TARGET_FPS`, `MAX_FRAME_SIDE`) |
| About 0.16 s per frame (median of 12 frames, one test image) on the dev Mac's CPU | Measured by us during development; **not recorded in the repo**. Re-measure on the Space before quoting it |
| CPU Upgrade costs $0.03 an hour (8 vCPU, 32 GB) | `hf spaces hardware` output; about $0.72 a day if left running |
| 7 Doha venues, 166 seats (8 live-configured, 158 simulated) | `venues/*.json` |
| 3 seat states, 3-frame smoothing, 30 s hold timer in demo mode (30 min in production) | `birdie/config.py` (`DEMO_TIMERS`, `PRODUCTION_TIMERS`), `birdie/vision/state.py` |
| Camera goes "offline" after 10 s without a frame and seats keep their last state | `birdie/config.py` (`camera_stale_seconds`), `tests/test_vision.py` |
| 75 automated tests pass | `pytest -q` |
| Frames are never written to disk (checked by a test) and people are blurred in every frame shown | `tests/test_architecture.py`, `tests/test_vision.py`, `birdie/vision/render.py` |
| The API answers in about 0.6 s per request (median 0.60 s) from a laptop in Doha to the Space | `python scripts/smoke_test.py` (re-run before submitting) |
| The app takes no bookings, no accounts, no personal data | `birdie/` has no booking or account code (`tests/test_architecture.py`) |
| Venue-side value: live occupancy, held-seat staff alerts, occupancy by hour, minutes held, peak times | Operator console: `birdie/ui/dashboard.py`, `birdie/alerts.py` |
| Survey results | **Only** the numbers we collect in the room (CLAUDE.md section 13) |

## 5. Claims we must not make

- **Any seat-state accuracy number.** None has been measured on real footage. The tools exist
  (`docs/LABELLING.md`, `jobs/evaluate.py`); the only run was on a 4-frame test clip. If labelling finishes and the job
  runs, quote exactly its `results.md`, with the failure cases.
- **"No images ever leave the venue."** True only as the production design (model on a device at the venue). In this
  demo the clip is uploaded to the Hugging Face Space, processed in memory and deleted after playback. Hugging Face
  logging and retention are not verified by us. Say "frames are processed in memory, blurred on screen, never stored".
- **That Nestwork is a live camera.** It is a recorded clip played through the pipeline in real time. (The app's About
  text currently says "live from a camera in the room": see the report.)
- **That the other venues are real data.** They are simulated, with synthetic history.
- **Anything about forecasts or "likely free when you arrive".** The forecast isn't in the app; it runs on synthetic
  history and hasn't been checked against real data. The backtest numbers in `jobs/results/` are on synthetic data and
  mean nothing about real accuracy.
- **That we use more than one model, or that we fine-tuned.** One detector, used as is. Chronos is optional and off.
- **Real users, partners, or savings** (minutes or money). We have none. Don't invent them.
- **That it costs nothing.** The Space costs $0.03 an hour and has no sleep time set, so it bills while it runs.
- **That a seat is guaranteed.** Birdie shows what's free now; someone can still take it before you arrive.
- **That an HF Job has run** unless one actually has, and **that a dataset is published** unless it is.
