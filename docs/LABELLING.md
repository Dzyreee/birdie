# Labelling frames for the Birdie accuracy test

Thank you for helping! You will look at frames from short clips of tables and say, for each seat, whether
someone is sitting there, whether only their things are there, or whether it is empty. Birdie's detector
is then scored against your answers. Budget about **20 minutes per clip**.

**Privacy:** the tool never saves the original video frames. It saves copies where people are pixelated.
Don't share the source videos (the `eval_clips` folder) with anyone.

## 1. One-time setup (10 minutes)

**Install uv** (it installs Python and everything else for you):

- **Mac:** open the Terminal app and paste:
  ```
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
  Then close the Terminal window and open a new one.
- **Windows:** open PowerShell (Start menu → type "PowerShell") and paste:
  ```
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
  Then close PowerShell and open a new one.

**Get the code.** If you have git:
```
git clone https://github.com/Dzyreee/birdie.git
cd birdie
```
No git? Open https://github.com/Dzyreee/birdie, click **Code → Download ZIP**, unzip it, then in the
Terminal/PowerShell type `cd ` (with a space), drag the unzipped `birdie` folder into the window, and press Enter.

**Add the clips.** Copy the phone videos into the `eval_clips` folder inside `birdie` (create it if it isn't there).
Any of .mp4, .mov, .m4v, .avi, .mkv or .webm works. If a video doesn't show up or won't open, re-export it as
H.264 ("Most Compatible" on iPhone).

## 2. Start the labelling tool

From the `birdie` folder:
```
uv run tools/label_app.py
```
The first start downloads about 1 GB (Python, PyTorch, the detector) and can take a few minutes. Later starts take
seconds. Your browser opens **http://127.0.0.1:7861** (open it yourself if it doesn't). Leave the Terminal window
open while you work; press `Ctrl+C` in it to stop the tool.

Type your name at the top, then pick a clip in the **Clip** list (press **↻ Refresh clips** if you just added one).

## 3. Step 1 · Draw the seats (once per clip)

1. Click **🖼 Show first frame**. The first frame appears with people pixelated.
2. For each seat you want to label, click its **4 corners**. Draw the area of **the chair plus the table area directly
   in front of it** (where that person's laptop, cup or bag would be). Don't overlap neighbouring seats.
3. Click **💾 Save seat**. The seat gets a number on the picture and the next id (S01, S02, ...) fills in by itself.
   Made a mistake? **↺ Redo corners** before saving, or pick the seat in **Seat to delete** after saving.
4. When every seat is drawn, click **▶ Extract frames** (keep 2 seconds between frames unless told otherwise).
   Wait for "✅ ... frames ready".

Only draw seats that stay visible in most of the clip. Drawing them is quick, but don't change them after you start
labelling.

## 4. Step 2 · Label the frames

Open the **Step 2 · Label frames** tab. You see one frame with numbered seats, and one row of buttons per seat.
For every seat pick one answer, then **Save & next ▶**. Your work is saved after every frame, so you can stop and
come back any time (**⏭ First unlabelled frame** takes you back to where you were).

Labels from the previous frame are pre-filled to save time (the line above the picture says "pre-filled"). **Check
every seat before saving**: change anything that is different in this frame.

### Keyboard shortcuts

| Key | Does |
|---|---|
| `1` or `P` | Person |
| `2` or `I` | Items only |
| `3` or `E` | Empty |
| `4` or `U` | Unclear |
| `↓` / `↑` | Move to the next / previous seat (the highlighted one is set by the keys above) |
| `Enter` or `→` | Save & next |
| `←` | Back |

After a label key, the highlight moves to the next seat on its own, so a frame is usually: `P` `E` `I` `Enter`.

## 5. The rules

Label **only what you see in this frame**, even if you know what happened before or after. (A person who has just
walked away and left their bag is "Items only" now. Birdie works out the timing itself.)

| Answer | When |
|---|---|
| **Person** | Someone is **sitting** on the seat, or clearly **leaning on it or kneeling on it**, even if partly hidden. A pixelated blob in the seat counts. |
| **Items only** | No person, but **belongings** are on the seat or on the **table area in front of it**: bag, backpack, laptop, phone, cup, bottle, book, jacket on the chair, and so on. |
| **Empty** | No person and no belongings. Things that belong to the venue (menus, napkins, sugar, table numbers, chairs pushed in) don't count. |
| **Unclear** | You honestly can't tell: the seat is blocked by someone standing in front, too dark, blurred by motion, or out of the picture. |

Tricky cases:

- **A person standing next to the seat, or walking past it, is Empty** (or Items only if their things are on it),
  unless they are sitting or leaning on it.
- **A bag on the table in front of a seat counts as Items only** for that seat, even if the chair is pushed in.
- **Something between two seats** belongs to the seat it is closer to. If it is exactly in the middle, choose the
  seat whose drawn area covers more of it.
- **Someone sitting with their things** is Person (Person always wins over Items only).
- **A jacket hanging on the chair** is Items only.
- **Two people sharing one seat area** is Person.
- When in doubt between two answers, pick **Unclear**. Unclear answers are left out of the score, so they never hurt it.

### If you can see a person who is NOT pixelated

Click **🗑 Remove frame (a person is not pixelated)**. This deletes the picture from the disk and skips the frame.
Don't take screenshots of frames.

## 6. When you are done

Tell Yacine, and send him the **`eval_data`** folder (zip it). **Don't send `eval_clips`**: those are the original
videos and stay on your computer. The `eval_data` folder only has pixelated frames, numbers and your answers.

## For Yacine: from labels to the score

```bash
# 1. Merge the eval_data folders you received into eval_data/ (one sub-folder per clip), then check locally:
uv run jobs/evaluate.py                                  # writes eval_data/results/results.{json,md}

# 2. Upload the labelled data to a PRIVATE dataset (pixelated frames, detections, seats, labels only):
scripts/push_eval_dataset.sh <owner>/birdie-eval

# 3. Run the evaluation as an HF Job on cpu-basic (20 min timeout); results land in the dataset's results/:
scripts/run_eval_job.sh <owner>/birdie-eval
```

The job only scores stored detections (the detector already ran on the original frames, in memory, during
extraction), so it needs no GPU and finishes in seconds.
