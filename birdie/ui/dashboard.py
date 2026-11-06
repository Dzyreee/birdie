"""Venue dashboard tab: occupancy by hour, minutes held by belongings and peak times (nothing else)."""

from __future__ import annotations

import gradio as gr
import pandas as pd

from birdie.analytics import venue_dashboard
from birdie.models import VenueSource
from birdie.service import BirdieService
from birdie.ui.common import esc, source_badge

WINDOWS = {"Last hour": 1, "Last 6 hours": 6, "Last 24 hours": 24}


def _tile(label: str, value: str, sub: str = "") -> str:
    return (
        f"<div class='birdie-card' style='flex:1;min-width:150px'>"
        f"<div class='birdie-muted'>{esc(label)}</div><div style='font-size:1.8em;font-weight:700'>{esc(value)}</div>"
        f"<div class='birdie-muted'>{esc(sub)}</div></div>"
    )


def dashboard_outputs(svc: BirdieService, venue_id: str, window: str):
    hours = WINDOWS.get(window, 24)
    now = svc.clock.now()
    v = svc.venue(venue_id)
    seat_ids = [s.seat_id for s in svc.seats(venue_id)]
    d = venue_dashboard(svc.repo, venue_id, seat_ids, now, hours=hours, observed_since=svc.observed_since(venue_id))
    peak = ", ".join(f"{p['hour']:02d}:00" for p in d.peak_hours) or "–"
    tiles = "<div style='display:flex;gap:10px;flex-wrap:wrap'>" + "".join([
        _tile("Held by belongings", f"{d.held_minutes_total:.0f} min", f"{window.lower()}, all seats"),
        _tile("Peak times", peak, f"since {d.start.strftime('%a %H:%M')}"),
    ]) + "</div>"
    header = f"### {esc(v.name)} {source_badge(v)}"
    notes = list(d.notes)
    if v.source == VenueSource.simulated:
        notes.append("Simulated venue: seat states come from the simulator, not a camera.")
    else:
        notes.append("Live venue: numbers come only from what the camera saw since the app started.")
    header += "\n\n" + " ".join(f"<span class='birdie-muted'>{esc(n)}</span>" for n in notes)

    occ = pd.DataFrame(
        [{"Hour": f"{r['hour']:02d}", "Occupied (%)": r["occupied_pct"]} for r in d.occupancy_by_hour
         if r["occupied_pct"] is not None],
        columns=["Hour", "Occupied (%)"],
    )
    held = sorted(d.held_minutes_by_seat.items(), key=lambda kv: -kv[1])[:10]
    held_df = pd.DataFrame([{"Seat": sid, "Minutes held": m} for sid, m in held], columns=["Seat", "Minutes held"])
    return header, tiles, occ, held_df


def build_dashboard_tab(svc: BirdieService, demo: gr.Blocks) -> None:
    venues = svc.venues()
    with gr.Row():
        venue_dd = gr.Dropdown(choices=[(v.name, v.venue_id) for v in venues], value=venues[0].venue_id,
                               label="Venue", scale=3)
        window = gr.Dropdown(choices=list(WINDOWS), value="Last 24 hours", label="Window", scale=1)
    header = gr.Markdown()
    tiles = gr.HTML()
    with gr.Row():
        occ_plot = gr.BarPlot(x="Hour", y="Occupied (%)", title="Occupancy by hour of day",
                              y_lim=[0, 100], height=280, x_title="Hour of day", y_title="Seats occupied or held (%)")
        held_plot = gr.BarPlot(x="Seat", y="Minutes held", title="Minutes held by belongings (top seats)",
                               height=280, sort="-y", y_lim=[0, None])
    outputs = [header, tiles, occ_plot, held_plot]

    def update(venue_id, window_v):
        return dashboard_outputs(svc, venue_id, window_v)

    venue_dd.change(update, [venue_dd, window], outputs)
    window.change(update, [venue_dd, window], outputs)
    gr.Timer(10.0).tick(update, [venue_dd, window], outputs, show_progress="hidden")
    demo.load(update, [venue_dd, window], outputs)
