# Overnight report

Branch: `overnight` (from `origin/main` at `0a4a320`, "Add place photos…"). Nothing was merged to `main`, nothing was
deployed, the Space and its settings were not touched (reads only: plain GETs and `hf spaces info`). No token was
printed or written. I did not edit `web/`, `design/` or `birdie/vision/`.

## 1. Secrets: nothing found

Searched the current tracked files and every commit on every branch for `hf_`, `github_pat_`, `ghp_`/`gho_`/`ghs_`,
`sk-`, AWS and Slack key patterns, private-key blocks, `token=`/`password=`-style assignments, and for `.env`, `.pem`,
`.key`, `credentials`, `secrets.*` files ever committed. **Zero hits.** `.env` is gitignored.
Nothing to revoke. (`HF_TOKEN` appears only as an environment-variable name in scripts.)

## 2. Live smoke test: 12/12 passed

`scripts/smoke_test.py` (GET only, standard library). Run at 01:36 Doha time against https://affaad-birdie.hf.space:

| Check | Result | Time |
|---|---|---|
| `/` loads | pass | 1.13 s |
| `/app.js` | pass | 0.83 s |
| `/operator/` loads | pass | 1.46 s |
| `/api/venues`: 7 venues, section 7.2 shape | pass | 0.81 s |
| `/api/venues/{id}` for all 7: floor plan, seats, valid statuses, timezone-aware `since`, counts match seats | pass | 0.58 to 0.60 s each |
| `/api/venues/does-not-exist` returns 404 | pass | 0.6 s |

Median 0.60 s, max 1.46 s. Nestwork: `camera_online=False`, 8 free (normal with no clip playing).
**Run it again before submitting:** `python scripts/smoke_test.py` (exit code 1 if anything fails; `--slow N` warns on
slow responses). It has an offline test (`tests/test_smoke_script.py`) so it can't drift from the API.

## 3. Tests and restart behaviour

- Full suite: **77 pass** (75 before, plus 2 for the smoke script). Nothing was failing.
- **What happens to Nestwork when the Space restarts or is redeployed:**
  - `venues/nestwork-msheireb.json` in the repo has **0 camera outlines** (8 seats, all with an empty `polygon`).
    Outlines made in the operator console live only on the Space's disk, so **a restart or deploy loses them**.
  - After a restart Nestwork shows 8 free chairs and `camera_online: false` until someone uploads the clip, runs
    "Detect chairs", saves, and presses Play again. The SQLite history (dashboard) is also lost on restart.
  - The Nestwork floor plan is still the placeholder (2 tables of 4), not the real room.
  - **Fix for the morning:** once the outlines are right, copy the JSON from the console's "Venue JSON" box into
    `venues/nestwork-msheireb.json`, commit, deploy. Then a restart keeps the outlines (you only need to re-upload the clip).

## 4. README rewritten for judges (header unchanged)

Every statement was checked against the code or `hf` output. It states plainly: only Nestwork is live and it runs from a
recorded clip, the six other venues are simulated, the forecast isn't in the app and isn't validated, and **no accuracy
number is claimed** (none has been measured on real footage).

## 5. Submission pack: `docs/SUBMISSION.md`

Sheet text for every column, a 7-shot 2-minute video script with voiceover, an 8-slide outline, a table of numbers we can
claim (each with its source), and a list of claims we must not make.

## 6. Cleanups

No booking, check-in, QR or assistant code is left outside the guarded folders (the guard tests enforce it). The mismatches
were in `CLAUDE.md`, now fixed in small edits: repo layout (added `chairs.py`, `clip.py`, `alerts.py`, `venues.py`,
`evaluation.py`, `tools/`, `scripts/`), `Query` is not removed (the doc said it was), section 7.3 now lists all 7
venues, section 16 is marked done, the cost line no longer says "with a sleep time", and the demo script no longer tells
us to say "no images ever leave the venue".

## Findings that need your attention

1. **The Space has no sleep time** (`hf spaces info`: `sleep_time` None). It bills $0.03/h around the clock (about
   $0.72/day). Earlier I said it sleeps after 15 minutes: that was wrong for the Docker Space. That is good for the demo
   (no cold start) but it costs money until someone pauses it. `Affaad/birdiee` (Daffa's test Space) should be checked the same way.
2. **The live Space is behind `main`.** It runs the code from `995f287`. Omair's later commit `0a4a320` (place photos,
   no Live/Simulated tags, logo on splash) is on `main` but **not deployed**.
3. **The app's About text says "Nestwork Msheireb is live from a camera in the room"** (`web/app.js`, line 427).
   Our footage is a recorded clip. Suggestion for Omair: "Nestwork Msheireb runs from footage recorded in the room,
   processed live by Birdie. The other places are simulated…". With the Live/Simulated tags gone from the list rows, the
   About tab and the pitch are the only places we say the other venues are simulated.
4. **"No images ever leave the venue" is not true for this demo**: the clip is uploaded to the Space (in memory, deleted
   after playback). It is only the production design. I removed it from the demo script and listed it under claims not to make.
5. **Suggestion for Omair:** use `camera_online` from the API. When it is `false`, show "Camera offline" on Nestwork,
   otherwise a restarted Space shows 8 free chairs that nobody is watching.
6. **Operator PIN:** I can't see the Space's variables, so I can't tell whether `BIRDIE_OPERATOR_PIN` is set. If it
   isn't, anyone who finds `/operator/` can play a clip into Nestwork. The Space owner can set it in the Space settings.
7. **Forecast task (paused):** you interrupted it, so no forecast code changed. What I found on
   `davnas/real-time-library-occupancy`: values are integer occupancy percentages (0 to 100), local Stockholm time,
   unsorted (2 rows out of order), sampled about every 190 s, one gap of 4.7 days (23 to 28 Jun 2025). Opening hours:
   Mon to Thu 08 to 20, Fri to 18, Sat about 10 to 15, **Sunday always 0**; nothing above 0 outside 08 to 21.
   **Activity stops on 23 Jun 2025; every reading from 24 Jun to 31 Jul is zero**, so "the last 4 weeks" would be all
   zeros and any model would look perfect. A fair test set is the 4 weeks before 23 Jun (26 May to 23 Jun), which is
   also the end-of-term wind-down, so results there will be pessimistic. The raw data is in `data/external/kth/`
   (gitignored, never to be re-uploaded). I installed `pyarrow` in the local venv only (not in `requirements.txt`).
   Decision for you: run the task on that adjusted test window?

## Waiting for your decision

- Team name for the sheet (`[Team Birdie]` is a placeholder).
- Whether to set a sleep time or leave the Space always on until the deadline (cost vs cold start).
- Whether Omair changes the About text and uses `camera_online`.
- Whether to commit the Nestwork outlines and the real floor plan to the repo (needs a sketch of the room).
- Whether to resume the forecast task with the adjusted test window (point 7) or drop it.

## Morning commands

```bash
cd ~/Desktop/birdie
git fetch --all --prune
git switch main && git pull --rebase
git log --oneline main..origin/overnight          # review what I added (docs, smoke test, one test, no app code)
git merge --ff-only origin/overnight              # if main moved and this fails: git merge origin/overnight
.venv/bin/python -m pytest -q                     # expect 77 passed (more if teammates added tests)
git push origin main

HF_TOKEN=$SPACE_TOKEN scripts/deploy_space.sh affaad/birdie
hf spaces logs affaad/birdie --build --follow     # wait for RUNNING (about 3 to 5 minutes)
python scripts/smoke_test.py                      # all checks should pass

# then, in https://affaad-birdie.hf.space/operator/: upload the clip, Detect chairs, Save, Play (Loop on)
python scripts/smoke_test.py                      # Nestwork should show camera_online=True
```

If the deploy shows a problem, the previous version is any earlier commit: `git switch --detach <sha>` then
`scripts/deploy_space.sh affaad/birdie` (the script uploads only the checked-out commit).
