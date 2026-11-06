"""Small helpers shared by the Gradio tabs."""

from __future__ import annotations

import html
from datetime import datetime

import numpy as np

from birdie.models import SeatState, Venue, VenueSource
from birdie.vision import render

STATE_ICON = {SeatState.FREE: "🟢", SeatState.OCCUPIED: "🔴", SeatState.HELD: "🟠"}

CSS = """
#birdie-webcam video { filter: blur(22px) saturate(0.6); }
.birdie-frame img { width: 100%; height: auto; border-radius: 10px; display: block; }
.birdie-frame { min-height: 120px; }
.birdie-setup { cursor: crosshair; width: 100%; height: auto; border-radius: 10px; display: block; }
.badge { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 0.78em; font-weight: 600;
         vertical-align: middle; margin-left: 6px; }
.badge-sim { background: #fde68a; color: #78350f; }
.badge-live { background: #bbf7d0; color: #14532d; }
.badge-syn { background: #e9d5ff; color: #581c87; }
.birdie-card { border: 1px solid var(--border-color-primary); border-radius: 12px; padding: 12px 14px; margin-bottom: 10px; }
.birdie-card h3 { margin: 0 0 4px 0; }
.birdie-muted { color: var(--body-text-color-subdued); font-size: 0.9em; }
.birdie-zones span { display: inline-block; margin-right: 10px; }
.focus-bar { background: var(--border-color-primary); border-radius: 6px; height: 8px; overflow: hidden; }
.focus-bar > div { background: #22c55e; height: 8px; }
"""

# Clicking the setup snapshot sends normalised (x, y) to Python through the HTML component's click event.
SETUP_CLICK_JS = """
element.addEventListener('click', (e) => {
  const img = e.target.closest('img.birdie-setup');
  if (!img) return;
  const r = img.getBoundingClientRect();
  const x = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
  const y = Math.min(1, Math.max(0, (e.clientY - r.top) / r.height));
  trigger('click', {x: x, y: y});
});
"""


def frame_html(frame: np.ndarray | None, css_class: str = "", text: str = "No frame yet") -> str:
    """An in-memory <img> (data URL) for a frame. Nothing is cached on disk."""
    if frame is None:
        frame = render.placeholder(text=text)
    uri = render.to_data_uri(frame)
    cls = f' class="{css_class}"' if css_class else ""
    return f'<div class="birdie-frame"><img{cls} src="{uri}" alt="annotated camera frame"/></div>'


def source_badge(venue: Venue) -> str:
    if venue.source == VenueSource.simulated:
        return '<span class="badge badge-sim">Simulated</span>'
    if venue.source == VenueSource.recorded:
        return '<span class="badge badge-sim">Recorded clip</span>'
    return '<span class="badge badge-live">Live camera</span>'


def esc(text: object) -> str:
    return html.escape(str(text))


def ago(since: datetime, now: datetime) -> str:
    secs = int((now - since).total_seconds())
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m {secs % 60:02d}s"
    return f"{secs // 3600}h {(secs % 3600) // 60:02d}m"
