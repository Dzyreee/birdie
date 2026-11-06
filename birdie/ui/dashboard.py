"""Venue dashboard tab: occupancy by hour, minutes held by belongings and peak times."""

from __future__ import annotations

import gradio as gr
import pandas as pd

from birdie.analytics import venue_dashboard
from birdie.models import SeatState, VenueSource
from birdie.service import BirdieService
from birdie.ui.common import esc, source_badge

# Validated categorical slots 1-3 (dataviz reference palette), fixed order by day type.
DAY_COLORS = {"Sun-Thu": "#2a78d6", "Friday": "#eb6834", "Saturday": "#1baf7a"}
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
    counts = svc.counts(venue_id)
    total = sum(counts.values())
    known = total - counts[SeatState.UNKNOWN] - counts[SeatState.UNAVAILABLE]
    occ_now = (
        counts[SeatState.OCCUPIED] + counts[SeatState.HELD] + counts[SeatState.REVIEW_REQUIRED]
    ) / known if known else None
    peak = ", ".join(f"{p['hour']:02d}:00" for p in d.peak_hours) or "–"
    tiles = "<div style='display:flex;gap:10px;flex-wrap:wrap'>" + "".join([
        _tile("Observed occupancy", f"{occ_now:.0%}" if occ_now is not None else "–",
              f"{counts[SeatState.FREE]} free · {counts[SeatState.UNKNOWN]} unknown · {counts[SeatState.UNAVAILABLE]} unavailable"),
        _tile("Held by belongings", f"{d.held_minutes_total:.0f} min",
              f"{window.lower()} · {counts[SeatState.HELD]} held · {counts[SeatState.REVIEW_REQUIRED]} need review"),
        _tile("Peak times", peak, f"since {d.start.strftime('%a %H:%M')}"),
    ]) + "</div>"
    header = f"### {esc(v.name)} {source_badge(v)}"
    notes = list(d.notes)
    if v.source == VenueSource.simulated:
        notes.append("Simulated venue: seat states come from the simulator, not a camera.")
    elif v.source == VenueSource.recorded:
        notes.append("Recorded-clip venue: seat states come from uploaded video, not a live camera feed.")
    else:
        notes.append("Live camera venue: numbers come only from camera evidence received by this app.")
    header += "\n\n" + " ".join(f"<span class='birdie-muted'>{esc(n)}</span>" for n in notes)

    occ = pd.DataFrame(
        [{"Hour": f"{r['hour']:02d}", "Occupied (%)": r["occupied_pct"]} for r in d.occupancy_by_hour
         if r["occupied_pct"] is not None],
        columns=["Hour", "Occupied (%)"],
    )
    held = sorted(d.held_minutes_by_seat.items(), key=lambda kv: -kv[1])[:10]
    held_df = pd.DataFrame([{"Seat": sid, "Minutes held": m} for sid, m in held])
    typical = []
    for day_type, label in (("weekday", "Sun-Thu"), ("friday", "Friday"), ("saturday", "Saturday")):
        for hour, ratio in svc.forecast.typical_day(venue_id, day_type):
            typical.append({"Hour": hour, "Occupied (%)": round(100 * ratio, 1), "Day": label})
    typical_df = pd.DataFrame(typical)

    alerts = svc.repo.alerts(venue_id, limit=8)
    alerts_df = pd.DataFrame(
        [[a["ts"].strftime("%H:%M:%S"), a["seat_id"], a["message"], "resolved" if a["resolved"] else "open"]
         for a in alerts],
        columns=["Time", "Seat", "Alert", "Status"],
    )
    return header, tiles, occ, held_df, typical_df, alerts_df


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
    typical_plot = gr.LinePlot(
        x="Hour", y="Occupied (%)", color="Day", color_map=DAY_COLORS, y_lim=[0, 100], height=280,
        title="Typical day by day type (synthetic history + live buckets, baseline forecaster)",
        x_title="Hour of day", y_title="Seats occupied (%)",
    )
    alerts_df = gr.Dataframe(label="Staff alerts", interactive=False)

    outputs = [header, tiles, occ_plot, held_plot, typical_plot, alerts_df]

    def update(venue_id, window_v):
        return dashboard_outputs(svc, venue_id, window_v)

    venue_dd.change(update, [venue_dd, window], outputs)
    window.change(update, [venue_dd, window], outputs)
    gr.Timer(10.0).tick(update, [venue_dd, window], outputs, show_progress="hidden")
    demo.load(update, [venue_dd, window], outputs)
