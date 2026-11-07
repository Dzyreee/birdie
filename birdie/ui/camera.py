"""Play uploaded clips through Birdie's seat-state pipeline and calibrate camera regions."""

from __future__ import annotations

import json
import os
import threading
import time

import gradio as gr
import numpy as np

from birdie.config import DEMO_MODE, TARGET_FPS
from birdie.models import Seat, SeatState
from birdie.service import BirdieService
from birdie.ui.common import esc, frame_html
from birdie.ui.seat_editor import build_seat_editor
from birdie.vision import render
from birdie.vision.clip import iter_clip_frames


class _CalibrationBackend:
    """Keep one calibration frame in memory; only seat polygons are saved."""

    def __init__(self, svc: BirdieService) -> None:
        self.svc = svc
        self.frames: dict[str, np.ndarray] = {}
        self.lock = threading.Lock()

    def set_frame(self, venue_id: str, frame: np.ndarray) -> None:
        with self.lock:
            self.frames[venue_id] = frame

    def frame(self, key: str, points: list[tuple[float, float]]) -> np.ndarray | None:
        with self.lock:
            frame = self.frames.get(key)
        return render.draw_seat_calibration(frame, self.seats(key), points) if frame is not None else None

    def seats(self, key: str) -> list[Seat]:
        return self.svc.seats(key)

    def zones(self, key: str) -> list[str]:
        return self.svc.venue(key).zones

    def upsert(self, key: str, seat: Seat) -> str:
        try:
            self.svc.upsert_seat(seat)
        except ValueError as exc:
            return str(exc)
        return f"Saved camera region for {seat.seat_id}. It remains hidden in the normal camera preview."

    def delete(self, key: str, seat_id: str) -> bool:
        return self.svc.delete_seat(key, seat_id)

    def export(self, key: str) -> str:
        return json.dumps([seat.model_dump(mode="json") for seat in self.seats(key)], indent=2)


def _status_html(svc: BirdieService, venue_id: str) -> str:
    counts = svc.counts(venue_id)
    study = svc.study_availability(venue_id)
    by_seat = {seat["seat_id"]: seat for seat in study["seats"]}
    reasons = {
        "camera_calibration_incomplete": "desk area needs calibration",
        "chair_not_visible": "chair not clearly visible",
        "workspace_uncertain": "desk area needs checking",
        "workspace_blocked": "desk area is blocked",
        "workspace_blocked_by_belongings": "belongings are present",
        "private_table_in_use_or_unverified": "private table is in use or unverified",
        "table_layout_incomplete": "table layout needs calibration",
        "table_unavailable": "table unavailable",
        "seat_not_linked_to_table": "seat is not linked to a table",
        "seat_occupied": "person detected at seat",
        "seat_unavailable": "seat unavailable",
    }
    rows = []
    for snap in svc.snapshots(venue_id):
        label = {
            SeatState.FREE: "Free",
            SeatState.OCCUPIED: "Taken",
            SeatState.HELD: "Held by belongings",
            SeatState.REVIEW_REQUIRED: "Staff review required",
            SeatState.UNKNOWN: "Checking",
            SeatState.UNAVAILABLE: "Unavailable",
        }[snap.state]
        countdown = (
            f" · staff review in {snap.grace_period_remaining_seconds}s"
            if snap.grace_period_remaining_seconds is not None else ""
        )
        result = by_seat.get(snap.seat_id, {})
        code = result.get("availability_reason", "not calibrated")
        detail = "Available for study" if result.get("usable_for_studying") else reasons.get(code, code.replace("_", " "))
        table = f" · {esc(result['table_id'])}" if result.get("table_id") else ""
        rows.append(f"<li><b>{esc(snap.seat_id)}</b>{table}: {esc(label + countdown)} · {esc(detail)}</li>")
    timer_note = "30s demo timer" if DEMO_MODE else "30m production timer"
    return (
        "<section class='birdie-card'>"
        f"<b>Verified usable study spaces: {study['usable_study_spaces']} ({study['usable_seats']} seats)</b><br>"
        f"Seat states: {counts[SeatState.FREE]} free · {counts[SeatState.OCCUPIED]} taken · "
        f"{counts[SeatState.HELD]} held · "
        f"Needs staff review: {counts[SeatState.REVIEW_REQUIRED]} · "
        f"Checking: {counts[SeatState.UNKNOWN]} · Unavailable: {counts[SeatState.UNAVAILABLE]}"
        f"<p class='birdie-muted'>Held belongings require staff review after the {timer_note}. "
        "Only seats marked Free count as available.</p>"
        f"<ul>{''.join(rows)}</ul></section>"
    )


def build_camera_tab(svc: BirdieService) -> None:
    if os.getenv("BIRDIE_DEMO_VIDEO", "").strip():
        gr.Markdown("The recorded demo runs automatically. The customer app shows seat states; "
                    "restart without `BIRDIE_DEMO_VIDEO` to edit calibration or inspect another clip.")
        return
    gr.Markdown(
        "Upload a short clip to run detections **through the seat-state backend**. "
        "The preview shows the original clip with object boxes only; seat regions are hidden. "
        "The uploaded file is deleted after analysis."
    )
    venues = svc.camera_venues()
    if not venues:
        gr.Markdown("No camera or recorded-clip venue is configured.")
        return

    venue = gr.Dropdown(
        choices=[(v.name, v.venue_id) for v in venues], value=venues[0].venue_id,
        label="Venue (chosen automatically when the clip is one of the two demo clips)",
    )
    clip = gr.File(label="Video clip (mp4, mov, webm)", file_types=["video"], type="filepath")
    loop = gr.Checkbox(value=False, label="Repeat clip to test the accelerated 30-second demo timer")
    with gr.Row():
        play_btn = gr.Button("▶ Test video → seat availability", variant="primary")
        stop_btn = gr.Button("■ Stop")
    annotated = gr.HTML(frame_html(None, text="Upload a clip and select Test video"), label="Camera preview")
    status = gr.HTML("Upload a clip to start the seat-state test.", label="Seat states")

    def play_clip(path, venue_id, loop_value):
        if not path:
            yield frame_html(None, text="Upload a clip first"), "Upload a clip to start the seat-state test."
            return
        from birdie.vision.demo import pause_for_venue, start_for_venue

        try:
            venue_id = svc.venue_for_clip(path) or venue_id  # the Msheireb and Corniche clips find their own venue
            pause_for_venue(svc, venue_id)  # the built-in replay of this venue steps aside while you test
            svc.validate_recording(venue_id, path)
            while True:
                svc.reset_alignment(venue_id)
                start = time.monotonic()
                for t, frame in iter_clip_frames(path, fps=TARGET_FPS):
                    annotated_frame = svc.process_frame(venue_id, frame, update_state=True)
                    yield frame_html(annotated_frame), _status_html(svc, venue_id)
                    delay = start + t + 1.0 / TARGET_FPS - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                if not loop_value:
                    break
        except Exception as exc:
            svc.mark_unknown(venue_id)
            yield frame_html(None, text="Video analysis failed"), (
                f"<div role='alert'>Video analysis failed: {esc(exc)}. "
                "Seat statuses were changed to Checking.</div>" + _status_html(svc, venue_id)
            )
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
            start_for_venue(svc, venue_id)  # hand the venue back to its built-in replay

    play_event = play_btn.click(
        play_clip, inputs=[clip, venue, loop], outputs=[annotated, status],
        concurrency_limit=1, show_progress="hidden",
    )
    stop_btn.click(None, cancels=[play_event])

    gr.Markdown(
        "The camera polygons below are backend calibration regions. They are separate from the "
        "customer floor map and are not drawn over the regular video preview."
    )
    calibration = _CalibrationBackend(svc)
    with gr.Accordion("Calibrate seats for this camera view", open=False):
        prepare = gr.Button("Use the first frame of this clip for calibration")
        editor = build_seat_editor(
            calibration, venue, snapshot_label="Show calibration frame",
            empty_text="Load a frame from the uploaded clip first",
            no_frame_message="Load a frame from the uploaded clip first.",
            json_label="Camera-region polygons (saved to venue config)",
            initial_key=venues[0].venue_id,
        )

        def prepare_frame(path, venue_id):
            if not path:
                return frame_html(None, css_class="birdie-setup", text="Upload a clip first"), [], "Upload a clip first."
            try:
                svc.validate_recording(venue_id, path)
                _, frame = next(iter_clip_frames(path, fps=TARGET_FPS))
            except (StopIteration, ValueError, OSError) as exc:
                return frame_html(None, css_class="birdie-setup", text="Could not read clip"), [], f"Could not read clip: {esc(exc)}"
            calibration.set_frame(venue_id, frame)
            ids = ", ".join(seat.seat_id for seat in svc.seats(venue_id)) or "none yet"
            return (
                frame_html(calibration.frame(venue_id, []), css_class="birdie-setup"), [],
                f"Frame loaded in memory. Existing seat ids: {esc(ids)}. Type an existing id to replace its region, "
                "or use a new id to add a seat; then click its four corners and save.",
            )

        prepare.click(prepare_frame, [clip, venue], [editor.image, editor.points, editor.message])

    gr.Markdown(
        "For a clean test: calibrate one seat around the chair and nearby table area, then replay a clip. "
        "A short clip can test detection and association; it cannot prove the real 30-minute rule."
    )
