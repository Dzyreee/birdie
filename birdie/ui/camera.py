"""Camera tab: live webcam, recorded clip, annotated view, seat setup tool, status tables."""

from __future__ import annotations

import json
import os
import time

import gradio as gr
import pandas as pd

from birdie.config import LIVE_VENUE_ID, TARGET_FPS
from birdie.service import BirdieService
from birdie.ui.common import STATE_ICON, ago, frame_html
from birdie.ui.seat_editor import build_seat_editor
from birdie.venues import zone_label
from birdie.vision.clip import iter_clip_frames

OPERATOR_PIN = os.getenv("BIRDIE_OPERATOR_PIN", "")

SEAT_COLUMNS = ["Seat", "Zone", "State", "For", "Outlet", "Bookable", "Booking"]
ZONE_COLUMNS = ["Zone", "Free", "Occupied", "Held", "Total"]


def seat_table(svc: BirdieService, venue_id: str) -> pd.DataFrame:
    now = svc.clock.now()
    seats = {s.seat_id: s for s in svc.seats(venue_id)}
    bookings = svc.active_booking_by_seat(venue_id) if hasattr(svc, "active_booking_by_seat") else {}
    rows = []
    for snap in svc.snapshots(venue_id):
        seat = seats.get(snap.seat_id)
        b = bookings.get(snap.seat_id)
        rows.append(
            [
                snap.seat_id,
                zone_label(snap.zone),
                f"{STATE_ICON[snap.state]} {snap.state.value}",
                ago(snap.since, now),
                "⚡" if snap.has_outlet else "",
                "✓" if seat and seat.bookable else "",
                b.status.value if b else "",
            ]
        )
    return pd.DataFrame(rows, columns=SEAT_COLUMNS)


def zone_table(svc: BirdieService, venue_id: str) -> pd.DataFrame:
    rows = [
        [zone_label(z), c["FREE"], c["OCCUPIED"], c["HELD"], c["total"]]
        for z, c in svc.zone_counts(venue_id).items()
    ]
    return pd.DataFrame(rows, columns=ZONE_COLUMNS)


class _ServiceSeats:
    """Seat editor backend for the live service (venue seats in venues/<venue_id>.json)."""

    def __init__(self, svc: BirdieService) -> None:
        self.svc = svc

    def frame(self, key, points):
        return self.svc.setup_frame(key, points)

    def seats(self, key):
        return self.svc.seats(key)

    def zones(self, key):
        return self.svc.venue(key).zones

    def upsert(self, key, seat):
        self.svc.upsert_seat(seat)
        return f"Saved seat **{seat.seat_id}** to venues/{key}.json."

    def delete(self, key, seat_id):
        return self.svc.delete_seat(key, seat_id)

    def export(self, key):
        return json.dumps(self.svc.configs[key].model_dump(mode="json"), indent=2, ensure_ascii=False)


def build_camera_tab(svc: BirdieService) -> None:
    cam_venues = [(v.name, v.venue_id) for v in svc.camera_venues()]
    default_venue = LIVE_VENUE_ID if LIVE_VENUE_ID in svc.configs else (cam_venues[0][1] if cam_venues else None)

    gr.Markdown(
        "Frames are processed **in memory** and discarded: never stored, never logged. "
        "People are blurred in every frame shown, including this operator view. Only seat states are kept."
    )
    with gr.Row():
        venue_dd = gr.Dropdown(choices=cam_venues, value=default_venue, label="Camera venue", scale=2)
        feed_state = gr.Checkbox(value=True, label="Update live seat states from this camera", scale=2)
        pin = gr.Textbox(
            label="Operator PIN", type="password", visible=bool(OPERATOR_PIN), scale=1,
        )

    with gr.Row():
        with gr.Column(scale=2):
            with gr.Tabs():
                with gr.Tab("Live webcam"):
                    webcam = gr.Image(
                        sources=["webcam"],
                        streaming=True,
                        type="numpy",
                        # Ask the browser for ~640x480 so frames stay small on the wire.
                        webcam_options=gr.WebcamOptions(
                            mirror=False,
                            constraints={"video": {"width": {"ideal": 640}, "height": {"ideal": 480}}},
                        ),
                        label="Webcam (preview blurred; ~1 frame per second is analysed)",
                        elem_id="birdie-webcam",
                        height=260,
                    )
                with gr.Tab("Recorded clip"):
                    clip = gr.File(label="Upload a clip (mp4, mov, webm)", file_types=["video"], type="filepath")
                    loop = gr.Checkbox(value=False, label="Loop until stopped")
                    with gr.Row():
                        play_btn = gr.Button("▶ Play through Birdie", variant="primary")
                        stop_btn = gr.Button("■ Stop")
                    gr.Markdown(
                        "<span class='birdie-muted'>The clip is sampled at 1 frame per second and played in real time, "
                        "so the hold and no-show timers behave as live. It is deleted from the server after playback.</span>"
                    )
        with gr.Column(scale=3):
            annotated = gr.HTML(frame_html(None, text="Start the webcam or play a clip"), label="Annotated view")

    with gr.Row():
        seats_df = gr.Dataframe(value=seat_table(svc, default_venue) if default_venue else None,
                                headers=SEAT_COLUMNS, interactive=False, label="Seats", scale=3)
        zones_df = gr.Dataframe(value=zone_table(svc, default_venue) if default_venue else None,
                                headers=ZONE_COLUMNS, interactive=False, label="Zones", scale=2)
    alerts_md = gr.Markdown()

    # --- seat setup tool ------------------------------------------------------------
    with gr.Accordion("Seat setup tool", open=False):
        gr.Markdown(
            "1. **Take snapshot** (one frame from the camera, memory only, people blurred). "
            "2. Click the **4 corners** of a seat. 3. Fill in the details and **Save seat**. "
            "Saving an existing seat id replaces it."
        )
        build_seat_editor(
            _ServiceSeats(svc),
            venue_dd,
            no_frame_message="No camera frame yet. Start the webcam (or play a clip), then take a snapshot.",
            empty_text="Take a snapshot first",
            json_label="Venue JSON (copy this into venues/ in the repo: the Space disk is not permanent)",
            default_zone="open",
            initial_key=default_venue,
        )

    # --- handlers -----------------------------------------------------------------
    def allowed(feed: bool, pin_value: str) -> bool:
        return bool(feed) and (not OPERATOR_PIN or pin_value == OPERATOR_PIN)

    def on_frame(frame, venue_id, feed, pin_value):
        if frame is None or not venue_id:
            return gr.skip()
        out = svc.process_frame(venue_id, frame, update_state=allowed(feed, pin_value))
        return frame_html(out)

    webcam.stream(
        on_frame,
        inputs=[webcam, venue_dd, feed_state, pin],
        outputs=[annotated],
        stream_every=1.0 / TARGET_FPS,
        concurrency_limit=1,
        show_progress="hidden",
    )

    def play_clip(path, venue_id, feed, pin_value, loop_value):
        if not path:
            yield frame_html(None, text="Upload a clip first")
            return
        try:
            while True:
                start = time.monotonic()
                for t, frame in iter_clip_frames(path, fps=TARGET_FPS):
                    out = svc.process_frame(venue_id, frame, update_state=allowed(feed, pin_value))
                    yield frame_html(out)
                    delay = start + t + 1.0 / TARGET_FPS - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                if not loop_value:
                    break
        except ValueError as exc:
            yield frame_html(None, text=str(exc))
        finally:
            try:
                os.remove(path)  # privacy: do not keep the uploaded clip on the server
            except OSError:
                pass

    play_event = play_btn.click(
        play_clip, inputs=[clip, venue_dd, feed_state, pin, loop], outputs=[annotated],
        concurrency_limit=1, show_progress="hidden",
    )
    stop_btn.click(None, cancels=[play_event])

    def refresh(venue_id):
        if not venue_id:
            return gr.skip(), gr.skip(), gr.skip()
        alerts = svc.repo.alerts(venue_id, unresolved_only=True, limit=5)
        md = ""
        if alerts:
            md = "**Staff alerts**\n\n" + "\n".join(
                f"- ⚠️ {a['ts'].strftime('%H:%M:%S')}: {a['message']}" for a in alerts
            )
        return seat_table(svc, venue_id), zone_table(svc, venue_id), md

    timer = gr.Timer(1.0)
    timer.tick(refresh, inputs=[venue_dd], outputs=[seats_df, zones_df, alerts_md], show_progress="hidden")
