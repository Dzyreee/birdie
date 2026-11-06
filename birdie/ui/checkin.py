"""QR check-in: opening the app with ?checkin=<booking_id> marks the booking QR_SCANNED."""

from __future__ import annotations

import gradio as gr

from birdie.booking import BookingError
from birdie.models import BookingStatus
from birdie.service import BirdieService
from birdie.ui.common import esc


def booking_banner(svc: BirdieService, booking_id: str | None, error: str | None = None) -> str:
    if error:
        return f"### ⚠️ Check-in\n{esc(error)}"
    if not booking_id:
        return ""
    b = svc.bookings.get(booking_id)
    if b is None:
        return "### ⚠️ Check-in\nUnknown booking."
    venue = svc.venue(b.venue_id).name
    window = svc.timers.checkin_window_seconds
    prepaid = f" · {esc(b.prepaid_item)}" if b.prepaid_item else ""
    if b.status == BookingStatus.QR_SCANNED:
        return (
            f"### 📱 QR scanned: seat **{esc(b.seat_id)}** at {esc(venue)}{prepaid}\n"
            f"Sit down: the camera confirms the seat is occupied within {window} s. "
            "It only checks that the seat is taken, never who is sitting there."
        )
    if b.status == BookingStatus.CHECKED_IN:
        return f"### ✅ Checked in: seat **{esc(b.seat_id)}** at {esc(venue)}{prepaid}\nVerified by the camera. Enjoy your study session."
    if b.status == BookingStatus.NO_SHOW_RELEASED:
        return f"### ⏱ Seat {esc(b.seat_id)} at {esc(venue)} was released to walk-ins\nThe seat wasn't occupied in time."
    return f"### Booking {esc(b.booking_id)}: {esc(b.status.value)}"


def build_checkin(svc: BirdieService, demo: gr.Blocks) -> None:
    banner = gr.Markdown(visible=False, elem_classes=["birdie-card"])
    booking_state = gr.State(None)

    def on_load(request: gr.Request):
        params = dict(getattr(request, "query_params", {}) or {})
        booking_id = (params.get("checkin") or "").strip()
        if not booking_id:
            return gr.update(visible=False), None
        try:
            svc.bookings.scan_qr(booking_id)
            return gr.update(value=booking_banner(svc, booking_id), visible=True), booking_id
        except BookingError as exc:
            return gr.update(value=booking_banner(svc, None, str(exc)), visible=True), None

    demo.load(on_load, inputs=None, outputs=[banner, booking_state])

    def poll(booking_id):
        if not booking_id:
            return gr.skip()
        return gr.update(value=booking_banner(svc, booking_id), visible=True)

    gr.Timer(2.0).tick(poll, [booking_state], [banner], show_progress="hidden")
