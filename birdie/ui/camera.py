"""Run the object detector over an uploaded video clip."""

from __future__ import annotations

import os
import time

import gradio as gr

from birdie.config import TARGET_FPS
from birdie.service import BirdieService
from birdie.ui.common import frame_html
from birdie.vision.clip import iter_clip_frames


def build_camera_tab(svc: BirdieService) -> None:
    gr.Markdown(
        "Upload a clip to see the model's chair, person, and belongings detections on the original video. "
        "This checks object detection; it does not label chairs free or occupied. "
        "The clip is shown without blurring and deleted after playback."
    )
    clip = gr.File(label="Video clip (mp4, mov, webm)", file_types=["video"], type="filepath")
    loop = gr.Checkbox(value=False, label="Loop until stopped")
    with gr.Row():
        play_btn = gr.Button("▶ Analyze clip", variant="primary")
        stop_btn = gr.Button("■ Stop")
    annotated = gr.HTML(frame_html(None, text="Upload a clip and select Analyze clip"), label="Detections")

    def play_clip(path, loop_value):
        if not path:
            yield frame_html(None, text="Upload a clip first")
            return
        try:
            while True:
                start = time.monotonic()
                for t, frame in iter_clip_frames(path, fps=TARGET_FPS):
                    yield frame_html(svc.process_frame(None, frame, update_state=False))
                    delay = start + t + 1.0 / TARGET_FPS - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                if not loop_value:
                    break
        except Exception as exc:
            yield frame_html(None, text=f"Video analysis failed: {exc}")
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    play_event = play_btn.click(
        play_clip, inputs=[clip, loop], outputs=[annotated], concurrency_limit=1, show_progress="hidden"
    )
    stop_btn.click(None, cancels=[play_event])
