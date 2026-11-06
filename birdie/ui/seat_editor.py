"""Seat-region editor used by the internal labelling tool.

Take a snapshot, click the 4 corners of a seat on it, fill in the details, save. Frames are shown as
in-memory data URLs (never cached on disk). The caller supplies a backend and a `key` component
    (the clip dropdown in the labelling tool).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

import gradio as gr
import numpy as np

from birdie.models import Seat
from birdie.ui.common import SETUP_CLICK_JS, frame_html


class SeatEditorBackend(Protocol):
    def frame(self, key: str, points: list[tuple[float, float]]) -> np.ndarray | None:
        """The snapshot with current seats and the clicked corners drawn, or None if there is no frame."""

    def seats(self, key: str) -> list[Seat]: ...

    def zones(self, key: str) -> list[str]: ...

    def upsert(self, key: str, seat: Seat) -> str:
        """Save the seat; return a message for the user."""

    def delete(self, key: str, seat_id: str) -> bool: ...

    def export(self, key: str) -> str:
        """The saved layout as JSON text."""


def next_seat_id(seats: list[Seat], prefix: str = "S") -> str:
    used = {s.seat_id for s in seats}
    numbers = [int(m.group(1)) for s in seats if (m := re.fullmatch(rf"{prefix}(\d+)", s.seat_id))]
    n = max(numbers, default=0) + 1
    while f"{prefix}{n:02d}" in used:
        n += 1
    return f"{prefix}{n:02d}"


@dataclass
class SeatEditor:
    image: gr.HTML
    points: gr.State
    seat_id: gr.Textbox
    zone: gr.Dropdown
    delete_dd: gr.Dropdown
    message: gr.Markdown
    layout_json: gr.Code

    def reset_outputs(self) -> list:
        return [self.image, self.points, self.zone, self.delete_dd, self.seat_id, self.layout_json]


def build_seat_editor(
    backend: SeatEditorBackend,
    key: gr.Component,
    *,
    snapshot_label: str = "📸 Take snapshot",
    empty_text: str = "Take a snapshot first",
    no_frame_message: str = "No frame yet.",
    show_details: bool = True,
    json_label: str = "Seat layout JSON",
    default_zone: str = "seat",
    initial_key: str | None = None,
) -> SeatEditor:
    """Build the editor inside the current Blocks context and wire its events."""
    init_seats = backend.seats(initial_key) if initial_key else []
    init_zones = (backend.zones(initial_key) if initial_key else []) or [default_zone]
    snap_btn = gr.Button(snapshot_label)
    image = gr.HTML(frame_html(None, css_class="birdie-setup", text=empty_text), js_on_load=SETUP_CLICK_JS)
    points = gr.State([])
    with gr.Row():
        seat_id = gr.Textbox(label="Seat id", placeholder="e.g. S07", value=next_seat_id(init_seats))
        zone = gr.Dropdown(choices=init_zones, value=init_zones[0], allow_custom_value=True, label="Zone",
                           visible=show_details)
        has_outlet = gr.Checkbox(label="Has outlet", visible=show_details)
    with gr.Row():
        save_btn = gr.Button("💾 Save seat", variant="primary")
        redo_btn = gr.Button("↺ Redo corners")
    with gr.Row():
        delete_dd = gr.Dropdown(choices=[s.seat_id for s in init_seats], label="Seat to delete")
        delete_btn = gr.Button("🗑 Delete seat", variant="stop")
    message = gr.Markdown()
    with gr.Accordion(json_label, open=False):
        layout_json = gr.Code(value=backend.export(initial_key) if initial_key else "", language="json",
                              interactive=False)

    def render(key_value, pts=None, text=empty_text):
        return frame_html(backend.frame(key_value, pts or []) if key_value else None, css_class="birdie-setup",
                          text=text)

    def seat_ids(key_value):
        return [s.seat_id for s in backend.seats(key_value)] if key_value else []

    def on_key(key_value):
        if not key_value:
            return gr.skip(), [], gr.skip(), gr.update(choices=[]), gr.skip(), ""
        zones = backend.zones(key_value) or [default_zone]
        return (
            render(key_value),
            [],
            gr.update(choices=zones, value=zones[0]),
            gr.update(choices=seat_ids(key_value), value=None),
            next_seat_id(backend.seats(key_value)),
            backend.export(key_value),
        )

    editor = SeatEditor(image, points, seat_id, zone, delete_dd, message, layout_json)
    key.change(on_key, [key], editor.reset_outputs())

    def take_snapshot(key_value):
        if not key_value or backend.frame(key_value, []) is None:
            return frame_html(None, css_class="birdie-setup", text=empty_text), [], no_frame_message
        return render(key_value), [], "Snapshot ready. Click the 4 corners of a seat."

    snap_btn.click(take_snapshot, [key], [image, points, message])

    def on_click(pts, key_value, evt: gr.EventData):
        data = getattr(evt, "_data", None) or {}
        if "x" not in data or not key_value or backend.frame(key_value, []) is None:
            return gr.skip(), pts, gr.skip()
        pts = list(pts or [])
        if len(pts) >= 4:
            return gr.skip(), pts, "4 corners already set. Save the seat or redo the corners."
        pts.append((round(float(data["x"]), 4), round(float(data["y"]), 4)))
        msg = f"Corner {len(pts)} of 4 set." + (" Now check the seat id and save." if len(pts) == 4 else "")
        return render(key_value, pts), pts, msg

    image.click(on_click, [points, key], [image, points, message])

    def redo(key_value):
        return render(key_value), [], "Corners cleared."

    redo_btn.click(redo, [key], [image, points, message])

    def save(pts, key_value, sid, zone_value, outlet):
        sid = (sid or "").strip()
        skip = (gr.skip(),) * 4
        if not key_value:
            return gr.skip(), pts, "Choose one first.", *skip
        if len(pts or []) != 4:
            return gr.skip(), pts, "Click exactly 4 corners first.", *skip
        if not sid:
            return gr.skip(), pts, "Give the seat an id.", *skip
        zone_value = str(zone_value or default_zone).strip()
        existing = next((s for s in backend.seats(key_value) if s.seat_id == sid), None)
        values = existing.model_dump() if existing else {}
        seat = Seat.model_validate({**values, "seat_id": sid, "venue_id": key_value, "zone": zone_value,
                                    "has_outlet": bool(outlet), "polygon": [tuple(p) for p in pts]})
        msg = backend.upsert(key_value, seat)
        return (
            render(key_value),
            [],
            msg,
            gr.update(choices=seat_ids(key_value)),
            next_seat_id(backend.seats(key_value)),
            backend.export(key_value),
        )

    save_btn.click(save, [points, key, seat_id, zone, has_outlet],
                   [image, points, message, delete_dd, seat_id, layout_json])

    def delete(key_value, sid):
        if not key_value or not sid:
            return gr.skip(), "Choose a seat to delete.", gr.skip(), gr.skip()
        ok = backend.delete(key_value, sid)
        return (
            render(key_value),
            f"Deleted seat **{sid}**." if ok else f"Seat {sid} not found.",
            gr.update(choices=seat_ids(key_value), value=None),
            backend.export(key_value),
        )

    delete_btn.click(delete, [key, delete_dd], [image, message, delete_dd, layout_json])
    return editor
