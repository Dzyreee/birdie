# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#   "gradio==6.31.0",
#   "torch",
#   "torchvision",
#   "transformers>=5.0,<6",
#   "pillow",
#   "numpy",
#   "shapely>=2.0",
#   "pydantic>=2.6",
#   "opencv-python-headless",
#   "pandas",
# ]
#
# [[tool.uv.index]]
# name = "pytorch-cpu"
# url = "https://download.pytorch.org/whl/cpu"
# explicit = true
#
# [tool.uv.sources]
# torch = { index = "pytorch-cpu" }
# torchvision = { index = "pytorch-cpu" }
# ///
"""Birdie labelling tool (runs locally): `uv run tools/label_app.py`, then open http://127.0.0.1:7861

Step 1: pick a clip from eval_clips/, draw its seats on the first frame (people pixelated, memory only), extract frames.
Step 2: label every seat in every frame as Person, Items only, Empty or Unclear. Saved after every frame.

Original frames are never saved: only copies with people pixelated are written to eval_data/<clip_id>/frames/.
See docs/LABELLING.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cv2  # noqa: E402
import gradio as gr  # noqa: E402
import numpy as np  # noqa: E402

from birdie.evaluation import (  # noqa: E402
    LABEL_NAMES,
    NAME_TO_LABEL,
    VIDEO_SUFFIXES,
    append_labels,
    append_removed,
    clip_id_from_path,
    load_clip,
    load_seats,
    save_seats,
    seats_path,
)
from birdie.models import Seat  # noqa: E402
from birdie.ui.common import CSS, frame_html  # noqa: E402
from birdie.ui.seat_editor import build_seat_editor  # noqa: E402
from birdie.vision.render import draw_numbered_seats, draw_setup_points  # noqa: E402
from extract_frames import CLIPS_DIR, DEFAULT_EVERY, EVAL_ROOT, iter_extract, preview_frame  # noqa: E402

MAX_SEATS = 12
CHOICES = [LABEL_NAMES[k] for k in ("person", "items", "empty", "unclear")]

LABEL_CSS = CSS + """
.seat-radio { padding: 6px 10px !important; }
.seat-radio label { font-size: 1.05rem !important; padding: 10px 18px !important; min-width: 120px; justify-content: center; }
.active-seat { box-shadow: 0 0 0 3px #f59e0b !important; border-radius: 10px; }
#label-progress { font-size: 1.1rem; }
"""

# Keyboard: 1/P Person, 2/I Items only, 3/E Empty, 4/U Unclear (then move to the next seat),
# up/down choose the seat, Enter or right arrow = Save & next, left arrow = Back.
SHORTCUTS_JS = """
() => {
  const KEYS = {'1': 'Person', 'p': 'Person', '2': 'Items only', 'i': 'Items only',
                '3': 'Empty', 'e': 'Empty', '4': 'Unclear', 'u': 'Unclear'};
  let active = 0;
  const radios = () => [...document.querySelectorAll('[id^="seat-radio-"]')].filter(el => el.offsetParent !== null);
  const highlight = () => radios().forEach((el, i) => el.classList.toggle('active-seat', i === active));
  const resetSoon = () => { active = 0; setTimeout(highlight, 400); setTimeout(highlight, 1200); };
  document.addEventListener('change', (e) => {
    const rs = radios();
    const i = rs.findIndex(el => el.contains(e.target));
    if (i >= 0) { active = Math.min(i + 1, rs.length - 1); highlight(); }
  });
  document.addEventListener('keydown', (e) => {
    const t = e.target;
    if (t && (t.tagName === 'TEXTAREA' || (t.tagName === 'INPUT' && t.type !== 'radio' && t.type !== 'checkbox'))) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const rs = radios();
    if (!rs.length) return;
    const k = e.key.toLowerCase();
    if (KEYS[k]) {
      const cur = Math.min(active, rs.length - 1);
      const input = [...rs[cur].querySelectorAll('input[type="radio"]')].find(x => x.value === KEYS[k]);
      if (input) input.click();
      active = Math.min(cur + 1, rs.length - 1);  // same target as the change listener: no double step
      highlight();
      e.preventDefault();
    } else if (e.key === 'Enter' || e.key === 'ArrowRight') {
      document.querySelector('#next-btn')?.click(); resetSoon(); e.preventDefault();
    } else if (e.key === 'ArrowLeft') {
      document.querySelector('#back-btn')?.click(); resetSoon(); e.preventDefault();
    } else if (e.key === 'ArrowDown') {
      active = Math.min(active + 1, rs.length - 1); highlight(); e.preventDefault();
    } else if (e.key === 'ArrowUp') {
      active = Math.max(active - 1, 0); highlight(); e.preventDefault();
    }
  });
  setInterval(() => { if (!document.querySelector('.active-seat')) highlight(); }, 1500);
}
"""


# --- data helpers --------------------------------------------------------------------

def clip_files() -> dict[str, Path]:
    if not CLIPS_DIR.exists():
        return {}
    files = sorted(p for p in CLIPS_DIR.iterdir() if p.suffix.lower() in VIDEO_SUFFIXES)
    return {clip_id_from_path(p): p for p in files}


def clip_choices() -> list[tuple[str, str]]:
    files = clip_files()
    extracted = {p.name for p in EVAL_ROOT.glob("*") if (p / "frames").is_dir()} if EVAL_ROOT.exists() else set()
    ids = sorted(set(files) | extracted)
    out = []
    for cid in ids:
        d = EVAL_ROOT / cid
        if (d / "frames").is_dir():
            clip = load_clip(d)
            status = f"{len(clip.frames)} frames, {len(clip.labels)} labelled"
        elif seats_path(d).exists():
            status = f"{len(load_seats(d))} seats drawn, not extracted"
        else:
            status = "new"
        out.append((f"{cid} · {status}", cid))
    return out


def read_rgb(path: Path) -> np.ndarray | None:
    bgr = cv2.imread(str(path))
    return None if bgr is None else cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


class EvalSeats:
    """Seat editor backend: seats live in eval_data/<clip_id>/seats.json."""

    def __init__(self) -> None:
        self._previews: dict[str, np.ndarray] = {}  # pixelated first frames, memory only

    def base(self, clip_id: str) -> np.ndarray | None:
        first = EVAL_ROOT / clip_id / "frames" / "000000.jpg"
        if first.exists():
            return read_rgb(first)
        if clip_id not in self._previews:
            path = clip_files().get(clip_id)
            if path is None:
                return None
            self._previews[clip_id] = preview_frame(path)
        return self._previews[clip_id]

    def frame(self, key, points):
        img = self.base(key)
        if img is None:
            return None
        return draw_setup_points(draw_numbered_seats(img, self.seats(key)), points)

    def seats(self, key):
        return load_seats(EVAL_ROOT / key)

    def zones(self, key):
        return ["seat"]

    def upsert(self, key, seat):
        seats = [s for s in self.seats(key) if s.seat_id != seat.seat_id] + [seat]
        save_seats(EVAL_ROOT / key, key, seats)
        return f"Saved seat **{seat.seat_id}** ({len(seats)} seats in eval_data/{key}/seats.json)."

    def delete(self, key, seat_id):
        seats = self.seats(key)
        kept = [s for s in seats if s.seat_id != seat_id]
        save_seats(EVAL_ROOT / key, key, kept)
        return len(kept) < len(seats)

    def export(self, key):
        p = seats_path(EVAL_ROOT / key)
        return p.read_text(encoding="utf-8") if p.exists() else json.dumps({"clip_id": key, "seats": []}, indent=2)


# --- step 2: labelling -----------------------------------------------------------------

def _radio_updates(seats: list[Seat], values: list[str | None]) -> list:
    ups = []
    for i in range(MAX_SEATS):
        if i < len(seats):
            ups.append(gr.update(visible=True, label=f"{i + 1} · {seats[i].seat_id}", value=values[i]))
        else:
            ups.append(gr.update(visible=False, value=None))
    return ups


def show(clip_id: str | None, i: int, copy_prev: bool, note: str = "") -> list:
    """Outputs: frame view, progress, index, then MAX_SEATS radio updates."""
    if not clip_id or not (EVAL_ROOT / clip_id / "frames").is_dir():
        msg = "Pick a clip, draw its seats and extract its frames in Step 1 first."
        return [frame_html(None, text="No frames yet"), msg, 0] + _radio_updates([], [])
    clip = load_clip(EVAL_ROOT / clip_id)
    n = len(clip.frames)
    if not n:
        return [frame_html(None, text="No frames"), "This clip has no frames.", 0] + _radio_updates([], [])
    if not clip.seats:
        return [frame_html(None, text="No seats"), "Draw the seats in Step 1 first.", 0] + _radio_updates([], [])
    i = max(0, min(int(i or 0), n - 1))
    f = clip.frames[i]
    seats = clip.seats[:MAX_SEATS]
    saved = clip.labels.get(f.frame_id)
    prefilled = False
    if saved is not None:
        values = [LABEL_NAMES.get(saved.get(s.seat_id), None) for s in seats]
    elif copy_prev and i > 0 and clip.frames[i - 1].frame_id in clip.labels:
        prev = clip.labels[clip.frames[i - 1].frame_id]
        values = [LABEL_NAMES.get(prev.get(s.seat_id), None) for s in seats]
        prefilled = any(values)
    else:
        values = [None] * len(seats)

    if f.frame_id in clip.removed or f.image_path is None:
        view = frame_html(None, text="Frame removed")
        values = [None] * len(seats)
    else:
        img = read_rgb(f.image_path)
        view = frame_html(draw_numbered_seats(img, seats) if img is not None else None, text="Missing image")

    done = len(clip.labels)
    status = ("✅ saved" if saved is not None else "🗑 removed" if f.frame_id in clip.removed
              else "✏️ pre-filled from the previous frame: check every seat" if prefilled else "not labelled yet")
    progress = (f"**Frame {i + 1} / {n}** · t = {f.t:.0f} s · {done} labelled, {len(clip.removed)} removed · {status}"
                + (f"\n\n{note}" if note else ""))
    if done + len(clip.removed) >= n and saved is not None:
        progress += "\n\n🎉 Every frame of this clip is done. Pick the next clip, or zip `eval_data/` and send it."
    return [view, progress, i] + _radio_updates(seats, values)


def first_unlabelled(clip_id: str | None) -> int:
    if not clip_id or not (EVAL_ROOT / clip_id / "frames").is_dir():
        return 0
    clip = load_clip(EVAL_ROOT / clip_id)
    for i, f in enumerate(clip.frames):
        if f.frame_id not in clip.labels and f.frame_id not in clip.removed:
            return i
    return max(0, len(clip.frames) - 1)


def save_current(clip_id: str, i: int, labeller: str, values: tuple) -> str | None:
    """Save the radios for frame i. Returns an error message if a seat is missing a label."""
    clip = load_clip(EVAL_ROOT / clip_id)
    f = clip.frames[int(i)]
    if f.frame_id in clip.removed:
        return None
    seats = clip.seats[:MAX_SEATS]
    missing = [f"{k + 1} ({s.seat_id})" for k, s in enumerate(seats) if not values[k]]
    if missing:
        return "⚠️ Label every seat first (use **Unclear** if you can't tell): seat " + ", ".join(missing)
    labels = {s.seat_id: NAME_TO_LABEL[values[k]] for k, s in enumerate(seats)}
    if clip.labels.get(f.frame_id) != labels:
        append_labels(EVAL_ROOT / clip_id, f.frame_id, labels, (labeller or "").strip())
    return None


def build_app() -> gr.Blocks:
    backend = EvalSeats()
    with gr.Blocks(title="Birdie labelling") as demo:
        gr.Markdown(
            "# 🐦 Birdie labelling tool\n"
            "Frames are saved **with people pixelated only**; the original frames are never written to disk. "
            "Instructions: `docs/LABELLING.md`."
        )
        with gr.Row():
            labeller = gr.Textbox(label="Your name (saved with your labels)", scale=1)
            clip_dd = gr.Dropdown(choices=clip_choices(), label="Clip (put video files in eval_clips/)", scale=3)
            refresh_btn = gr.Button("↻ Refresh clips", scale=0)

        with gr.Tabs():
            with gr.Tab("Step 1 · Draw seats"):
                gr.Markdown(
                    "1. **Show first frame**. 2. Click the **4 corners** of a seat: the chair and the table area right "
                    "in front of it. 3. **Save seat** (the id fills in by itself). Repeat for every seat you will label. "
                    "4. **Extract frames**."
                )
                build_seat_editor(
                    backend,
                    clip_dd,
                    snapshot_label="🖼 Show first frame",
                    empty_text="Pick a clip, then Show first frame",
                    no_frame_message="Pick a clip first (video files go in the eval_clips/ folder).",
                    show_details=False,
                    json_label="seats.json",
                    default_zone="seat",
                )
                with gr.Row():
                    every = gr.Number(value=DEFAULT_EVERY, label="Seconds between frames", minimum=0.5, maximum=30)
                    extract_btn = gr.Button("▶ Extract frames", variant="primary")
                extract_msg = gr.Markdown()

            with gr.Tab("Step 2 · Label frames") as label_tab:
                progress = gr.Markdown(elem_id="label-progress")
                with gr.Row():
                    with gr.Column(scale=3):
                        view = gr.HTML(frame_html(None, text="Pick a clip"))
                    with gr.Column(scale=2):
                        radios = [
                            gr.Radio(CHOICES, label=f"{k + 1}", visible=False, elem_id=f"seat-radio-{k}",
                                     elem_classes=["seat-radio"])
                            for k in range(MAX_SEATS)
                        ]
                with gr.Row():
                    back_btn = gr.Button("◀ Back", elem_id="back-btn", size="lg")
                    next_btn = gr.Button("Save & next ▶", variant="primary", elem_id="next-btn", size="lg")
                with gr.Row():
                    jump_btn = gr.Button("⏭ First unlabelled frame")
                    remove_btn = gr.Button("🗑 Remove frame (a person is not pixelated)", variant="stop")
                    copy_prev = gr.Checkbox(value=True, label="Pre-fill from the previous frame (then check every seat)")
                gr.Markdown(
                    "**Keyboard:** `1`/`P` Person · `2`/`I` Items only · `3`/`E` Empty · `4`/`U` Unclear "
                    "(then it moves to the next seat; the highlighted seat is the one being set) · `↑`/`↓` choose seat · "
                    "`Enter` or `→` save & next · `←` back."
                )
                idx = gr.State(0)

        outputs = [view, progress, idx, *radios]

        def on_refresh():
            return gr.update(choices=clip_choices())

        refresh_btn.click(on_refresh, None, [clip_dd])

        def on_clip(clip_id, copy):
            return show(clip_id, first_unlabelled(clip_id), copy)

        clip_dd.change(on_clip, [clip_dd, copy_prev], outputs)
        label_tab.select(lambda c, i, copy: show(c, i, copy), [clip_dd, idx, copy_prev], outputs)

        def do_extract(clip_id, every_s):
            if not clip_id:
                yield "Pick a clip first."
                return
            path = clip_files().get(clip_id)
            seats = load_seats(EVAL_ROOT / clip_id)
            if not seats:
                yield "Draw and save at least one seat first."
                return
            if path is None:
                yield f"The video for {clip_id} is not in eval_clips/."
                return
            yield "Loading the detector (the first time takes a minute)…"
            try:
                n = 0
                for n, total in iter_extract(path, EVAL_ROOT, clip_id, seats, float(every_s or DEFAULT_EVERY)):
                    yield f"Extracting {n} / {total} frames (people pixelated, originals not saved)…"
            except ValueError as exc:
                yield f"⚠️ {exc}"
                return
            clip = load_clip(EVAL_ROOT / clip_id)
            yield f"✅ {len(clip.frames)} frames ready in eval_data/{clip_id}/. Go to **Step 2 · Label frames**."

        extract_btn.click(do_extract, [clip_dd, every], [extract_msg]).then(on_refresh, None, [clip_dd])

        def go(delta: int, save_first: bool):
            def handler(clip_id, i, name, copy, *values):
                if not clip_id or not (EVAL_ROOT / clip_id / "frames").is_dir():
                    return show(clip_id, 0, copy)
                err = save_current(clip_id, i, name, values) if save_first else None
                if err and delta > 0:
                    return show_keep(clip_id, i, copy, err, values)
                return show(clip_id, int(i) + delta, copy)
            return handler

        def show_keep(clip_id, i, copy, note, values):
            out = show(clip_id, i, copy, note)
            seats = load_seats(EVAL_ROOT / clip_id)[:MAX_SEATS]
            return out[:3] + _radio_updates(seats, list(values[:len(seats)]) + [None] * (MAX_SEATS - len(seats)))

        inputs = [clip_dd, idx, labeller, copy_prev, *radios]
        next_btn.click(go(+1, True), inputs, outputs, show_progress="hidden")

        def back(clip_id, i, name, copy, *values):
            if clip_id and (EVAL_ROOT / clip_id / "frames").is_dir():
                save_current(clip_id, i, name, values)  # keeps complete labels; incomplete ones are not saved
            return show(clip_id, int(i or 0) - 1, copy)

        back_btn.click(back, inputs, outputs, show_progress="hidden")
        jump_btn.click(lambda c, copy: show(c, first_unlabelled(c), copy), [clip_dd, copy_prev], outputs)

        def remove(clip_id, i, name, copy):
            if not clip_id or not (EVAL_ROOT / clip_id / "frames").is_dir():
                return show(clip_id, 0, copy)
            clip = load_clip(EVAL_ROOT / clip_id)
            f = clip.frames[int(i)]
            if f.image_path and f.image_path.exists():
                f.image_path.unlink()  # privacy: delete the image itself
            append_removed(EVAL_ROOT / clip_id, f.frame_id, (name or "").strip())
            return show(clip_id, int(i) + 1, copy, f"🗑 Frame {int(i) + 1} removed and its image deleted.")

        remove_btn.click(remove, [clip_dd, idx, labeller, copy_prev], outputs)
    return demo


def main() -> None:
    p = argparse.ArgumentParser(description="Birdie labelling tool")
    p.add_argument("--port", type=int, default=7861)
    p.add_argument("--no-browser", action="store_true", help="don't open the browser automatically")
    args = p.parse_args()
    CLIPS_DIR.mkdir(exist_ok=True)
    EVAL_ROOT.mkdir(exist_ok=True)
    build_app().launch(server_name="127.0.0.1", server_port=args.port, inbrowser=not args.no_browser,
                       css=LABEL_CSS, js=SHORTCUTS_JS)


if __name__ == "__main__":
    main()
