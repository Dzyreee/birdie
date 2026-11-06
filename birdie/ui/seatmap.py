"""Seat map as inline SVG: seat polygons coloured by state, booked seats outlined. No images."""

from __future__ import annotations

from collections import defaultdict

from birdie.models import Booking, Seat, SeatSnapshot, SeatState, VenueSource
from birdie.venues import zone_label

FILL = {SeatState.FREE: "#22c55e", SeatState.OCCUPIED: "#ef4444", SeatState.HELD: "#f59e0b"}
BOOKED = "#2a78d6"
W, H = 1000, 600


def seat_map_svg(
    seats: list[Seat],
    snapshots: dict[str, SeatSnapshot],
    bookings: dict[str, Booking],
    source: VenueSource,
) -> str:
    parts = [
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="Seat map" style="width:100%;height:auto;background:var(--background-fill-secondary);'
        f'border-radius:12px">'
    ]
    zones: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for seat in seats:
        if len(seat.polygon) < 3:
            continue
        zones[seat.zone].extend(seat.polygon)
    for zone, pts in zones.items():
        x0 = min(p[0] for p in pts) * W
        y0 = min(p[1] for p in pts) * H
        x1 = max(p[0] for p in pts) * W
        y1 = max(p[1] for p in pts) * H
        parts.append(
            f'<rect x="{x0 - 8:.0f}" y="{y0 - 32:.0f}" width="{x1 - x0 + 16:.0f}" height="{y1 - y0 + 40:.0f}" '
            f'rx="10" fill="none" stroke="currentColor" stroke-opacity="0.18" stroke-dasharray="4 4"/>'
            f'<text x="{x0:.0f}" y="{y0 - 6:.0f}" font-size="24" fill="currentColor" fill-opacity="0.75">'
            f"{zone_label(zone)}</text>"
        )
    for seat in seats:
        if len(seat.polygon) < 3:
            continue
        snap = snapshots.get(seat.seat_id)
        state = snap.state if snap else SeatState.FREE
        booking = bookings.get(seat.seat_id)
        pts = " ".join(f"{x * W:.1f},{y * H:.1f}" for x, y in seat.polygon)
        stroke = f'stroke="{BOOKED}" stroke-width="4" stroke-dasharray="7 4"' if booking else 'stroke="white" stroke-width="2"'
        cx = sum(p[0] for p in seat.polygon) / len(seat.polygon) * W
        cy = sum(p[1] for p in seat.polygon) / len(seat.polygon) * H
        title = f"{seat.seat_id} · {zone_label(seat.zone)} · {state.value}"
        if seat.has_outlet:
            title += " · outlet"
        if booking:
            title += f" · booked ({booking.status.value})"
        parts.append(
            f'<g><title>{title}</title><polygon points="{pts}" fill="{FILL[state]}" fill-opacity="0.85" {stroke}/>'
            f'<text x="{cx:.0f}" y="{cy + 8:.0f}" text-anchor="middle" font-size="22" fill="white" '
            f'font-weight="600">{seat.seat_id}{" ⚡" if seat.has_outlet else ""}</text></g>'
        )
    parts.append("</svg>")
    caption = "Floor plan (simulated venue)" if source == VenueSource.simulated else "Camera-view layout (live)"
    legend = (
        '<div class="birdie-muted" style="margin-top:6px">'
        f'<span style="color:{FILL[SeatState.FREE]}">■</span> Free &nbsp; '
        f'<span style="color:{FILL[SeatState.OCCUPIED]}">■</span> Occupied &nbsp; '
        f'<span style="color:{FILL[SeatState.HELD]}">■</span> Held by belongings &nbsp; '
        f'<span style="color:{BOOKED}">▭</span> Booked &nbsp; ⚡ outlet &nbsp;·&nbsp; {caption}</div>'
    )
    return "".join(parts) + legend
