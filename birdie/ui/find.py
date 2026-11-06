"""Find a study venue by live seat availability, arrival time and preferences."""

from __future__ import annotations

import gradio as gr

from birdie.decision import AREA_COORDS, FocusScore, Recommendation, focus_score, recommend, zone_free_now
from birdie.models import Query, SeatState, VenueType
from birdie.service import BirdieService
from birdie.ui.common import esc, source_badge
from birdie.venues import zone_label

ANY = "Any"


def _score_bar(score: int) -> str:
    return f'<div class="focus-bar"><div style="width:{max(0, min(100, score))}%"></div></div>'


def breakdown_html(f: FocusScore) -> str:
    rows = "".join(
        f"<tr><td>{esc(p.label)}</td><td>{esc(p.value)}</td>"
        f"<td style='text-align:right'><b>{p.points:.0f}</b> / {p.weight}</td></tr>"
        for p in f.parts
    )
    return f"<table style='width:100%;font-size:0.9em'>{rows}</table>"


def venue_cards(svc: BirdieService, arrival: int) -> str:
    cards = []
    for v in svc.venues():
        snaps = svc.snapshots(v.venue_id)
        free = sum(1 for s in snaps if s.state == SeatState.FREE)
        unknown = sum(1 for s in snaps if s.state == SeatState.UNKNOWN)
        known = len(snaps) - unknown
        f = focus_score(svc, v.venue_id, arrival)
        zones = zone_free_now(svc, v.venue_id)
        zone_txt = "".join(f"<span>{esc(zone_label(z))}: <b>{n}</b></span>" for z, n in zones.items())
        cards.append(
            f"""<div class="birdie-card">
  <h3>{esc(v.name)} {source_badge(v)}</h3>
  <div class="birdie-muted">{esc(v.area)} · {esc(v.type.value)} · {v.noise_db:.0f} dB</div>
  <div style="margin:6px 0"><b style="font-size:1.4em">{free}</b> of {known} known seats free · {unknown} status unknown ·
     {esc(f.availability.summary())}</div>
  <div class="birdie-zones birdie-muted">Free by zone: {zone_txt}</div>
  <div style="margin-top:6px">Focus score <b>{f.score}</b>/100 {_score_bar(f.score)}</div>
  <details><summary class="birdie-muted">Why this score?</summary>{breakdown_html(f)}</details>
</div>"""
        )
    return "<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:10px'>" + "".join(cards) + "</div>"


def recommendations_html(recs: list[Recommendation]) -> str:
    if not recs:
        return "<div class='birdie-card'>No venue matches right now. Try a later arrival time or fewer filters.</div>"
    out = []
    for i, r in enumerate(recs, 1):
        reasons = "".join(f"<li>{esc(x)}</li>" for x in r.reasons)
        out.append(
            f"<div class='birdie-card'><h3>{i}. {esc(r.venue.name)} {source_badge(r.venue)}</h3>"
            f"<div>Focus score <b>{r.focus.score}</b>/100 {_score_bar(r.focus.score)}</div>"
            f"<ul style='margin:6px 0 0 18px'>{reasons}</ul>"
            f"<details><summary class='birdie-muted'>Score breakdown</summary>{breakdown_html(r.focus)}</details></div>"
        )
    return "".join(out)


def build_find_tab(svc: BirdieService, demo: gr.Blocks) -> None:
    venues = svc.venues()
    all_zones = sorted({z for v in venues for z in v.zones})
    areas = sorted({v.area for v in venues} | {a.title() for a in AREA_COORDS})

    gr.Markdown(
        "See live free seats by venue and zone. **Only Nestwork Msheireb is live**; "
        "the other venues are simulated demo data."
    )
    arrival = gr.Slider(0, 120, value=20, step=5, label="I'll arrive in (minutes)")
    cards = gr.HTML(venue_cards(svc, 20))
    gr.Timer(3.0).tick(lambda a: venue_cards(svc, int(a)), [arrival], [cards], show_progress="hidden")
    demo.load(lambda a: venue_cards(svc, int(a)), [arrival], [cards])

    gr.Markdown("### Find me a seat")
    with gr.Row():
        area = gr.Dropdown(choices=[ANY] + areas, value=ANY, allow_custom_value=True, label="Near")
        party = gr.Number(value=1, minimum=1, maximum=10, precision=0, label="People")
        vtype = gr.Dropdown(choices=[ANY] + [t.value for t in VenueType], value=ANY, label="Venue type")
        zone = gr.Dropdown(choices=[(ANY, ANY)] + [(zone_label(z), z) for z in all_zones], value=ANY, label="Zone")
    with gr.Row():
        outlet = gr.Checkbox(label="Needs an outlet")
        quiet = gr.Checkbox(label="Quiet")
        go = gr.Button("Find me a seat", variant="primary")
    results = gr.HTML()

    def do_recommend(area_v, party_v, vtype_v, zone_v, outlet_v, quiet_v, arrival_min):
        query = Query(
            area=None if area_v in (None, "", ANY) else area_v,
            party_size=max(1, int(party_v or 1)),
            needs_outlet=bool(outlet_v),
            quiet=bool(quiet_v),
            zone=None if zone_v in (None, "", ANY) else zone_v,
            venue_type=None if vtype_v in (None, "", ANY) else VenueType(vtype_v),
            arrival_minutes=int(arrival_min),
        )
        return recommendations_html(recommend(svc, query))

    go.click(do_recommend, [area, party, vtype, zone, outlet, quiet, arrival], [results])
