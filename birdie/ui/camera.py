"""Camera tab (operator console): play a recorded clip into the live venue, seat setup, seat status.

The camera input is an uploaded clip, sampled at 1 frame per second and played in real time so the hold
timer behaves as it would live. "Loop clip" keeps the live venue updating (otherwise it goes camera
offline 10 s after the clip ends). People are blurred in every frame shown. The webcam input from the
earlier version is kept behind BIRDIE_ENABLE_WEBCAM (off by default).
"""

from __future__ import annotations

import json
import os
import time

import gradio as gr
import pandas as pd

from birdie.config import LIVE_VENUE_ID, TARGET_FPS, WEBCAM_ENABLED
from birdie.models import SeatState
from birdie.service import BirdieService
from birdie.ui.common import frame_html
from birdie.ui.seat_editor import build_seat_editor
from birdie.vision.chairs import auto_number, natural_key
from birdie.vision.clip import clip_duration, frame_at, iter_clip_frames

OPERATOR_PIN = os.getenv("BIRDIE_OPERATOR_PIN", "")
MAX_CHAIRS = 20
STATE_ICON = {SeatState.FREE: "🟢", SeatState.OCCUPIED: "⚫", SeatState.HELD: "🟠"}
STATE_WORD = {SeatState.FREE: "Free", SeatState.OCCUPIED: "Taken", SeatState.HELD: "Held"}
SEAT_COLUMNS = ["Seat", "Table", "State", "For", "Outlet", "Window", "Camera outline"]


def _ago(seconds: float) -> str:
    secs = int(seconds)
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m {secs % 60:02d}s"
    return f"{secs // 3600}h {(secs % 3600) // 60:02d}m"


def seat_table(svc: BirdieService, venue_id: str) -> pd.DataFrame:
    now = svc.clock.now()
    seats = {s.seat_id: s for s in svc.seats(venue_id)}
    rows = []
    for snap in sorted(svc.snapshots(venue_id), key=lambda s: natural_key(s.seat_id)):
        seat = seats.get(snap.seat_id)
        rows.append([
            snap.seat_id,
            getattr(seat, "table_id", None) or "",
            f"{STATE_ICON[snap.state]} {STATE_WORD[snap.state]}",
            _ago((now - snap.since).total_seconds()),
            "⚡" if seat and seat.has_outlet else "",
            "🪟" if seat and getattr(seat, "has_window", False) else "",
            "✓" if seat and len(seat.polygon) >= 3 else "–",
        ])
    return pd.DataFrame(rows, columns=SEAT_COLUMNS)


def camera_status(svc: BirdieService, venue_id: str) -> str:
    online = svc.camera_online(venue_id)
    with_outline = sum(1 for s in svc.seats(venue_id) if len(s.polygon) >= 3)
    outlines = f"{with_outline} of {len(svc.seats(venue_id))} seats have a camera outline"
    if online:
        return f"🟢 **Camera online** · {outlines}"
    return (f"⚪ **Camera offline** (no frame in the last {svc.timers.camera_stale_seconds} s; seats keep their "
            f"last state) · {outlines}")


class _CameraSeats:
    """Seat editor backend: camera outlines saved into the venue's existing (floor-plan) seats."""

    def __init__(self, svc: BirdieService) -> None:
        self.svc = svc

    def frame(self, key, points):
        return self.svc.setup_view(key, points)

    def seats(self, key):
        return sorted(self.svc.seats(key), key=lambda s: natural_key(s.seat_id))

    def zones(self, key):
        return self.svc.venue(key).zones or ["open"]

    def upsert(self, key, seat):
        self.svc.set_seat_polygon(key, seat.seat_id, seat.polygon)
        return f"Saved the camera outline of seat **{seat.seat_id}** (floor-plan fields unchanged)."

    def delete(self, key, seat_id):
        return self.svc.clear_seat_polygon(key, seat_id)

    def export(self, key):
        return json.dumps(self.svc.configs[key].model_dump(mode="json"), indent=2, ensure_ascii=False)


def build_camera_tab(svc: BirdieService) -> None:
    cam_venues = [(v.name, v.venue_id) for v in svc.camera_venues()]
    default_venue = LIVE_VENUE_ID if LIVE_VENUE_ID in svc.configs else (cam_venues[0][1] if cam_venues else None)
    backend = _CameraSeats(svc)

    gr.Markdown(
        "Frames are processed **in memory** and discarded: never stored, never logged. People are blurred in every "
        "frame shown. Only seat states are kept. The uploaded clip is deleted from the server when playback stops."
    )
    with gr.Row():
        venue_dd = gr.Dropdown(choices=cam_venues, value=default_venue, label="Camera venue", scale=2)
        pin = gr.Textbox(label="Operator PIN", type="password", visible=bool(OPERATOR_PIN), scale=1)
    status_md = gr.Markdown(camera_status(svc, default_venue) if default_venue else "")

    with gr.Row():
        with gr.Column(scale=2):
            clip = gr.File(label="Recorded clip from the venue (mp4, mov, webm)", file_types=["video"], type="filepath")
            loop = gr.Checkbox(value=True, label="Loop clip (keeps the venue live during the demo)")
            with gr.Row():
                play_btn = gr.Button("▶ Play clip into Birdie", variant="primary")
                stop_btn = gr.Button("■ Stop")
            gr.Markdown(
                "<span class='birdie-muted'>Sampled at 1 frame per second and played in real time, so the hold timer "
                "behaves as live. Without Loop, the venue goes camera offline 10 s after the clip ends.</span>"
            )
            webcam = None
            if WEBCAM_ENABLED:  # earlier live-webcam input, off by default (BIRDIE_ENABLE_WEBCAM=1)
                webcam = gr.Image(
                    sources=["webcam"], streaming=True, type="numpy",
                    webcam_options=gr.WebcamOptions(
                        mirror=False, constraints={"video": {"width": {"ideal": 640}, "height": {"ideal": 480}}},
                    ),
                    label="Webcam (preview blurred; ~1 frame per second is analysed)", elem_id="birdie-webcam",
                    height=240,
                )
        with gr.Column(scale=3):
            annotated = gr.HTML(frame_html(None, text="Upload a clip and press Play"), label="Annotated view")

    seats_df = gr.Dataframe(value=seat_table(svc, default_venue) if default_venue else None, headers=SEAT_COLUMNS,
                            interactive=False, label="Seats")
    alerts_md = gr.Markdown()

    # --- seat setup: one seat per chair -------------------------------------------------
    with gr.Accordion("Seat setup: one seat per chair", open=False):
        gr.Markdown(
            "1. Upload the clip above. 2. Pick a moment where the chairs are visible and press **Detect chairs** "
            "(one frame, memory only, people blurred). Every chair gets a number. 3. Give each number the seat id "
            "from the floor plan (or **Auto-number left to right**, then fix), and **Save chair seats**. "
            "Only the camera outlines are saved; the floor plan is never changed. "
            "To fix one seat by hand, click its 4 corners below, pick the seat id and **Save seat**."
        )
        with gr.Row():
            snap_t = gr.Number(value=0, minimum=0, label="Snapshot at (seconds into the clip)")
            detect_btn = gr.Button("🪑 Detect chairs", variant="primary")
        editor = build_seat_editor(
            backend, venue_dd,
            snapshot_label="🔄 Refresh view",
            empty_text="Press Detect chairs first",
            no_frame_message="No snapshot yet: upload a clip and press Detect chairs.",
            show_details=False,
            json_label="Venue JSON (copy it into venues/ in the repo: the Space disk is not permanent)",
            default_zone="open",
            initial_key=default_venue,
            pick_existing=True,
        )
        gr.Markdown("**Detected chairs → floor-plan seats**")
        with gr.Row():
            auto_btn = gr.Button("🔢 Auto-number left to right")
            save_chairs_btn = gr.Button("💾 Save chair seats", variant="primary")
        with gr.Row():
            chair_dds = [
                gr.Dropdown(choices=[], value=None, label=f"Chair {i + 1}", visible=False, min_width=120)
                for i in range(MAX_CHAIRS)
            ]
        chairs_msg = gr.Markdown()

    # --- handlers -----------------------------------------------------------------
    def allowed(pin_value: str) -> bool:
        return not OPERATOR_PIN or (pin_value or "") == OPERATOR_PIN

    def play_clip(path, venue_id, loop_value, pin_value):
        if not allowed(pin_value):
            yield frame_html(None, text="Enter the operator PIN first")
            return
        if not path:
            yield frame_html(None, text="Upload a clip first")
            return
        try:
            while True:
                svc.reset_alignment(venue_id)  # the first frame of every pass is the reference for the outlines
                start = time.monotonic()
                for t, frame in iter_clip_frames(path, fps=TARGET_FPS):
                    yield frame_html(svc.process_frame(venue_id, frame, update_state=True))
                    delay = start + t + 1.0 / TARGET_FPS - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                if not loop_value:
                    break
        except Exception as exc:  # unreadable clip and the like
            yield frame_html(None, text=f"Video analysis failed: {exc}")
        finally:
            try:
                os.remove(path)  # privacy: do not keep the uploaded clip on the server
            except OSError:
                pass

    play_event = play_btn.click(play_clip, [clip, venue_dd, loop, pin], [annotated],
                                concurrency_limit=1, show_progress="hidden")
    stop_btn.click(None, cancels=[play_event])

    if webcam is not None:
        def on_frame(frame, venue_id, pin_value):
            if frame is None or not venue_id:
                return gr.skip()
            return frame_html(svc.process_frame(venue_id, frame, update_state=allowed(pin_value)))

        webcam.stream(on_frame, [webcam, venue_dd, pin], [annotated], stream_every=1.0 / TARGET_FPS,
                      concurrency_limit=1, show_progress="hidden")

    def refresh(venue_id):
        if not venue_id:
            return gr.skip(), gr.skip(), gr.skip()
        alerts = svc.repo.alerts(venue_id, unresolved_only=True, limit=5)
        md = ""
        if alerts:
            md = "**Staff alerts**\n\n" + "\n".join(
                f"- ⚠️ {a['ts'].strftime('%H:%M:%S')}: {a['message']}" for a in alerts
            )
        return seat_table(svc, venue_id), md, camera_status(svc, venue_id)

    gr.Timer(1.0).tick(refresh, [venue_dd], [seats_df, alerts_md, status_md], show_progress="hidden")

    def plan_ids(venue_id):
        return [s.seat_id for s in sorted(svc.seats(venue_id), key=lambda s: natural_key(s.seat_id))]

    def chair_updates(venue_id, values=None):
        n = len(svc.chair_candidates(venue_id)) if venue_id else 0
        ids = [""] + plan_ids(venue_id) if venue_id else []
        values = values or [None] * MAX_CHAIRS
        return [
            gr.update(visible=i < n, choices=ids, value=values[i] if i < n else None)
            for i in range(MAX_CHAIRS)
        ]

    def detect(venue_id, path, t, pin_value):
        if not allowed(pin_value):
            return [gr.skip(), "Enter the operator PIN first."] + [gr.skip()] * MAX_CHAIRS
        if not venue_id:
            return [gr.skip(), "Choose a venue."] + [gr.skip()] * MAX_CHAIRS
        frame = frame_at(path, float(t or 0)) if path else None
        if frame is None:
            msg = "Upload the clip first (it is deleted after playback, so upload it again if you played it)."
            return [gr.skip(), msg] + [gr.skip()] * MAX_CHAIRS
        n = svc.set_setup_frame(venue_id, frame)
        dur = clip_duration(path)
        msg = (f"Found **{n} chairs** at {float(t or 0):.1f} s" + (f" (clip is {dur:.0f} s long)" if dur else "")
               + ". Match each number to a floor-plan seat, or Auto-number left to right.")
        if n > MAX_CHAIRS:
            msg += f" Only the first {MAX_CHAIRS} can be mapped here; fix the rest by hand."
        return [frame_html(svc.setup_view(venue_id, []), css_class="birdie-setup"), msg] + chair_updates(venue_id)

    detect_btn.click(detect, [venue_dd, clip, snap_t, pin], [editor.image, chairs_msg, *chair_dds])

    def auto(venue_id):
        if not venue_id or not svc.chair_candidates(venue_id):
            return ["Detect chairs first."] + [gr.skip()] * MAX_CHAIRS
        ids = auto_number(svc.chair_candidates(venue_id), plan_ids(venue_id))
        values = ids + [None] * (MAX_CHAIRS - len(ids))
        return ["Numbered left to right. Check each one against the floor plan, then Save chair seats."] \
            + chair_updates(venue_id, values)

    auto_btn.click(auto, [venue_dd], [chairs_msg, *chair_dds])

    def save_chairs(venue_id, pin_value, *values):
        if not allowed(pin_value):
            return gr.skip(), "Enter the operator PIN first.", gr.skip()
        candidates = svc.chair_candidates(venue_id) if venue_id else []
        if not candidates:
            return gr.skip(), "Detect chairs first.", gr.skip()
        mapping = {}
        for i, cand in enumerate(candidates[:MAX_CHAIRS]):
            sid = values[i]
            if not sid:
                continue
            if sid in mapping:
                return gr.skip(), f"Seat **{sid}** is given to two chairs. Each chair needs its own seat.", gr.skip()
            mapping[sid] = cand["polygon"]
        if not mapping:
            return gr.skip(), "Give at least one chair a seat id.", gr.skip()
        svc.set_seat_polygons(venue_id, mapping)
        msg = f"Saved {len(mapping)} chair outlines: {', '.join(sorted(mapping, key=natural_key))}."
        return frame_html(svc.setup_view(venue_id, []), css_class="birdie-setup"), msg, backend.export(venue_id)

    save_chairs_btn.click(save_chairs, [venue_dd, pin, *chair_dds], [editor.image, chairs_msg, editor.layout_json])
