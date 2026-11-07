"""Birdie: Gradio entry point (UI only). All logic lives in the framework-free birdie/ package."""

from __future__ import annotations

import logging
import os
import threading

import gradio as gr
import uvicorn

from birdie.api import create_app, mount_mobile_web
from birdie.config import DEMO_MODE, LIVE_VENUE_ID, ROOT_DIR
from birdie.models import VenueSource
from birdie.service import BirdieService
from birdie.ui.camera import build_camera_tab
from birdie.ui.common import CSS
from birdie.ui.dashboard import build_dashboard_tab

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("birdie")

svc = BirdieService()
svc.start()  # background scheduler: seat timers, staff alerts and occupancy buckets


def _warm_up_detector() -> None:
    try:
        from birdie.vision.detector import load

        load()
    except Exception:
        log.exception("Detector warm-up failed; it will retry on the first frame")


threading.Thread(target=_warm_up_detector, daemon=True, name="detector-warmup").start()

# Recorded venues replay demo_clips/<venue_id>.mp4 when the file is on the Space (the clips are not in git;
# they are uploaded to the Space once and survive deploys). The venue config pins each clip by SHA-256.
for _cfg in svc.configs.values():
    _clip = ROOT_DIR / "demo_clips" / f"{_cfg.venue.venue_id}.mp4"
    if _cfg.venue.source == VenueSource.recorded and _clip.is_file():
        from birdie.vision.demo import start_recorded_demo as _start

        _start(svc, _cfg.venue.venue_id, str(_clip))

demo_video = os.getenv("BIRDIE_DEMO_VIDEO", "").strip()
if demo_video:
    from birdie.vision.demo import start_recorded_demo

    start_recorded_demo(svc, os.getenv("BIRDIE_DEMO_VENUE", LIVE_VENUE_ID), demo_video)

with gr.Blocks(title="Birdie") as demo:
    gr.Markdown(
        "# 🐦 Birdie\n"
        "**A bird's-eye view of every study seat in Doha before you drive there.** "
        "Study-seat availability from camera data and recorded demos."
        + (" &nbsp;<span class='badge badge-syn'>Demo timers</span>" if DEMO_MODE else "")
    )
    with gr.Tabs():
        with gr.Tab("Venue dashboard"):
            build_dashboard_tab(svc, demo)
        with gr.Tab("Camera"):
            build_camera_tab(svc)

app = create_app(svc)
app = gr.mount_gradio_app(app, demo, path="/operator", css=CSS)
mount_mobile_web(app)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)
