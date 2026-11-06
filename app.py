"""Birdie: Gradio entry point (UI only). All logic lives in the framework-free birdie/ package."""

from __future__ import annotations

import logging
import threading

import gradio as gr

from birdie.config import DEMO_MODE
from birdie.service import BirdieService
from birdie.ui.camera import build_camera_tab
from birdie.ui.common import CSS
from birdie.ui.dashboard import build_dashboard_tab
from birdie.ui.find import build_find_tab

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

with gr.Blocks(title="Birdie") as demo:
    gr.Markdown(
        "# 🐦 Birdie\n"
        "**A bird's-eye view of every study seat in Doha before you drive there.** "
        "Camera-verified live seats for cafes, libraries and study spaces."
        + (" &nbsp;<span class='badge badge-syn'>Demo timers</span>" if DEMO_MODE else "")
    )
    with gr.Tabs():
        with gr.Tab("Find a seat"):
            build_find_tab(svc, demo)
        with gr.Tab("Venue dashboard"):
            build_dashboard_tab(svc, demo)
        with gr.Tab("Camera"):
            build_camera_tab(svc)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, css=CSS)
