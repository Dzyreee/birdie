"""Video test tab: recorded clips, annotated view, seat setup tool, status tables."""

from __future__ import annotations

import json
import os
import time

import gradio as gr
import pandas as pd

from birdie.config import LIVE_VENUE_ID, TARGET_FPS
from birdie.models import Seat
from birdie.service import BirdieService
from birdie.ui.common import SETUP_CLICK_JS, STATE_ICON, ago, frame_html
from birdie.venues import zone_label
from birdie.vision.clip import iter_clip_frames

OPERATOR_PIN = os.getenv("BIRDIE_OPERATOR_PIN", "")

SEAT_COLUMNS = ["Seat", "Zone", "State", "For", "Outlet", "Bookable", "Booking"]
ZONE_COLUMNS = ["Zone", "Free", "Occupied", "Held", "Unknown", "Total"]


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
        [zone_label(z), c["FREE"], c["OCCUPIED"], c["HELD"], c["UNKNOWN"], c["total"]]
        for z, c in svc.zone_counts(venue_id).items()
    ]
    return pd.DataFrame(rows, columns=ZONE_COLUMNS)


def build_camera_tab(svc: BirdieService) -> None:
    cam_venues = [(v.name, v.venue_id) for v in svc.camera_venues()]
    default_venue = LIVE_VENUE_ID if LIVE_VENUE_ID in svc.configs else (cam_venues[0][1] if cam_venues else None)

    gr.Markdown(
        "Uploaded video is sent to this Space and shown without blurring. The clip file is deleted after playback; "
        "seat events and counts are stored in the app database. Hugging Face logging and retention are not verified."
    )
    with gr.Row():
        venue_dd = gr.Dropdown(choices=cam_venues, value=default_venue, label="Camera venue", scale=2)
        feed_state = gr.Checkbox(value=True, label="Update live seat states from this camera", scale=2)
        pin = gr.Textbox(
            label="Operator PIN", type="password", visible=bool(OPERATOR_PIN), scale=1,
        )

    with gr.Row():
        with gr.Column(scale=2):
            clip = gr.File(label="Upload a clip (mp4, mov, webm)", file_types=["video"], type="filepath")
            loop = gr.Checkbox(value=False, label="Loop until stopped")
            with gr.Row():
                play_btn = gr.Button("▶ Play through Birdie", variant="primary")
                stop_btn = gr.Button("■ Stop")
            gr.Markdown(
                "<span class='birdie-muted'>The clip is sampled at 1 frame per second and played in real time, "
                "so the hold and no-show timers behave as live. The uploaded file is deleted after playback.</span>"
            )
        with gr.Column(scale=3):
            annotated = gr.HTML(frame_html(None, text="Upload and play a clip"), label="Video analysis")

    with gr.Row():
        seats_df = gr.Dataframe(value=seat_table(svc, default_venue) if default_venue else None,
                                headers=SEAT_COLUMNS, interactive=False, label="Seats", scale=3)
        zones_df = gr.Dataframe(value=zone_table(svc, default_venue) if default_venue else None,
                                headers=ZONE_COLUMNS, interactive=False, label="Zones", scale=2)
    alerts_md = gr.Markdown()

    # --- seat setup tool ------------------------------------------------------------
    with gr.Accordion("Seat setup tool", open=False):
        gr.Markdown(
            "1. **Take snapshot** (one frame from the clip, kept in memory). "
            "2. Click the **4 corners** of a seat. 3. Fill in the details and **Save seat**. "
            "Saving an existing seat id replaces it."
        )
        snap_btn = gr.Button("📸 Take snapshot")
        setup_img = gr.HTML(
            frame_html(None, css_class="birdie-setup", text="Take a snapshot first"),
            js_on_load=SETUP_CLICK_JS,
        )
        points = gr.State([])
        with gr.Row():
            seat_id = gr.Textbox(label="Seat id", placeholder="e.g. S07")
            zone = gr.Dropdown(
                choices=svc.venue(default_venue).zones if default_venue else [],
                value=(svc.venue(default_venue).zones or [None])[0] if default_venue else None,
                allow_custom_value=True,
                label="Zone",
            )
            has_outlet = gr.Checkbox(label="Has outlet")
            bookable = gr.Checkbox(label="Bookable")
        with gr.Row():
            save_btn = gr.Button("💾 Save seat", variant="primary")
            redo_btn = gr.Button("↺ Redo corners")
        with gr.Row():
            del_dd = gr.Dropdown(
                choices=[s.seat_id for s in svc.seats(default_venue)] if default_venue else [],
                label="Seat to delete",
            )
            del_btn = gr.Button("🗑 Delete seat", variant="stop")
        setup_msg = gr.Markdown()
        with gr.Accordion("Venue JSON (copy this into venues/ in the repo: the Space disk is not permanent)", open=False):
            venue_json = gr.Code(language="json", interactive=False)

    # --- handlers -----------------------------------------------------------------
    def allowed(feed: bool, pin_value: str) -> bool:
        return bool(feed) and (not OPERATOR_PIN or pin_value == OPERATOR_PIN)

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

    def on_venue_change(venue_id):
        v = svc.venue(venue_id)
        return (
            gr.update(choices=v.zones, value=v.zones[0] if v.zones else None),
            gr.update(choices=[s.seat_id for s in svc.seats(venue_id)], value=None),
            [],
            frame_html(svc.setup_frame(venue_id), css_class="birdie-setup", text="Take a snapshot first"),
        )

    venue_dd.change(on_venue_change, [venue_dd], [zone, del_dd, points, setup_img])

    def take_snapshot(venue_id):
        frame = svc.setup_frame(venue_id, [])
        if frame is None:
            return frame_html(None, css_class="birdie-setup", text="Play a clip first"), [], \
                "No video frame yet. Play a clip, then take a snapshot."
        return frame_html(frame, css_class="birdie-setup"), [], "Snapshot taken. Click the 4 corners of a seat."

    snap_btn.click(take_snapshot, [venue_dd], [setup_img, points, setup_msg])

    def on_click(pts, venue_id, evt: gr.EventData):
        data = getattr(evt, "_data", None) or {}
        if "x" not in data or not svc.has_frame(venue_id):
            return gr.skip(), pts, gr.skip()
        pts = list(pts or [])
        if len(pts) >= 4:
            return gr.skip(), pts, "4 corners already set. Save the seat or redo the corners."
        pts.append((round(float(data["x"]), 4), round(float(data["y"]), 4)))
        frame = svc.setup_frame(venue_id, pts)
        msg = f"Corner {len(pts)} of 4 set." + (" Now fill in the details and save." if len(pts) == 4 else "")
        return frame_html(frame, css_class="birdie-setup"), pts, msg

    setup_img.click(on_click, [points, venue_dd], [setup_img, points, setup_msg])

    def redo(venue_id):
        return frame_html(svc.setup_frame(venue_id, []), css_class="birdie-setup", text="Take a snapshot first"), [], \
            "Corners cleared."

    redo_btn.click(redo, [venue_dd], [setup_img, points, setup_msg])

    def save(pts, venue_id, sid, zone_value, outlet, book):
        sid = (sid or "").strip()
        if len(pts or []) != 4:
            return gr.skip(), pts, "Click exactly 4 corners first.", gr.skip(), gr.skip()
        if not sid:
            return gr.skip(), pts, "Give the seat an id.", gr.skip(), gr.skip()
        if not zone_value:
            return gr.skip(), pts, "Choose a zone.", gr.skip(), gr.skip()
        seat = Seat(seat_id=sid, venue_id=venue_id, zone=str(zone_value).strip(), has_outlet=bool(outlet),
                    bookable=bool(book), polygon=[tuple(p) for p in pts])
        svc.upsert_seat(seat)
        return (
            frame_html(svc.setup_frame(venue_id, []), css_class="birdie-setup"),
            [],
            f"Saved seat **{sid}** to venues/{venue_id}.json.",
            gr.update(choices=[s.seat_id for s in svc.seats(venue_id)]),
            venue_json_text(venue_id),
        )

    def venue_json_text(venue_id):
        return json.dumps(svc.configs[venue_id].model_dump(mode="json"), indent=2, ensure_ascii=False)

    save_btn.click(save, [points, venue_dd, seat_id, zone, has_outlet, bookable],
                   [setup_img, points, setup_msg, del_dd, venue_json])

    def delete(venue_id, sid):
        if not sid:
            return gr.skip(), "Choose a seat to delete.", gr.skip(), gr.skip()
        ok = svc.delete_seat(venue_id, sid)
        return (
            frame_html(svc.setup_frame(venue_id, []), css_class="birdie-setup", text="Take a snapshot first"),
            f"Deleted seat **{sid}**." if ok else f"Seat {sid} not found.",
            gr.update(choices=[s.seat_id for s in svc.seats(venue_id)], value=None),
            venue_json_text(venue_id),
        )

    del_btn.click(delete, [venue_dd, del_dd], [setup_img, setup_msg, del_dd, venue_json])
