"""Birdie: one process on port 7860 (CLAUDE.md section 5).

  /           the mobile web app (static files from web/)
  /api/...    read-only JSON API (birdie/api.py)
  /operator   Gradio operator console: Camera and Venue dashboard

All live state lives in the one BirdieService below. Run: python app.py
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import gradio as gr
import uvicorn

from birdie.api import create_app, mount_web
from birdie.config import DEMO_MODE
from birdie.service import BirdieService
from birdie.ui.camera import build_camera_tab
from birdie.ui.common import CSS
from birdie.ui.dashboard import build_dashboard_tab

ROOT = Path(__file__).resolve().parent
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("birdie")

svc = BirdieService()
svc.start()  # simulated venues + background scheduler: seat timers, staff alerts, occupancy buckets


def _warm_up_detector() -> None:
    try:
        from birdie.vision.detector import load

        load()
    except Exception:
        log.exception("Detector warm-up failed; it will retry on the first frame")


threading.Thread(target=_warm_up_detector, daemon=True, name="detector-warmup").start()

with gr.Blocks(title="Birdie operator console") as console:
    gr.Markdown(
        "# 🐦 Birdie · operator console\n"
        "Camera-verified live seats. The customer app is at [/](/)."
        + (" &nbsp;<span class='badge badge-syn'>Demo timers</span>" if DEMO_MODE else "")
    )
    with gr.Tabs():
        with gr.Tab("Camera"):
            build_camera_tab(svc)
        with gr.Tab("Venue dashboard"):
            build_dashboard_tab(svc, console)

app = create_app(svc)
app = gr.mount_gradio_app(app, console, path="/operator", css=CSS, ssr_mode=False, pwa=False, max_file_size="500mb",
                          footer_links=[])
mount_web(app, ROOT / "web")  # last: catches every other path

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "7860")), log_level="info")
