"""Find a seat tab: live venue list, availability at arrival, focus score, recommend form, booking + QR."""

from __future__ import annotations

import gradio as gr

from birdie.booking import BookingError, checkin_url, make_qr_png
from birdie.decision import AREA_COORDS, FocusScore, Recommendation, focus_score, recommend, zone_free_now
from birdie.models import BookingStatus, Query, SeatState, VenueType
from birdie.service import BirdieService
from birdie.ui.common import esc, public_base_url, qr_html, source_badge
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


def recommendations_html(recs: list[Recommendation], query: Query) -> str:
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


def booking_html(svc: BirdieService, booking_id: str | None, base_url: str) -> str:
    if not booking_id:
        return ""
    b = svc.bookings.get(booking_id)
    if b is None:
        return ""
    venue = svc.venue(b.venue_id)
    url = checkin_url(base_url, b.booking_id)
    status_icon = {
        BookingStatus.BOOKED_PENDING: "🕒", BookingStatus.QR_SCANNED: "📱", BookingStatus.CHECKED_IN: "✅",
        BookingStatus.COMPLETED: "🏁", BookingStatus.NO_SHOW_RELEASED: "⏱", BookingStatus.CANCELLED: "✖",
    }[b.status]
    prepaid = f"<div>☕ {esc(b.prepaid_item)} <span class='birdie-muted'>(mocked payment)</span></div>" if b.prepaid_item else ""
    t = svc.timers
    help_txt = (
        f"Scan the QR on the table when you arrive. The camera confirms the seat is occupied within "
        f"{t.checkin_window_seconds} s. If the seat is still empty {t.no_show_seconds} s after your arrival time, "
        "it goes back to walk-ins. If camera status is unknown, the booking stays pending until the feed recovers."
    )
    return f"""<div class="birdie-card" style="display:flex;gap:16px;flex-wrap:wrap">
  {qr_html(make_qr_png(url))}
  <div style="flex:1;min-width:220px">
    <h3>{status_icon} {esc(b.status.value.replace('_', ' ').title())}</h3>
    <div><b>{esc(venue.name)}</b> {source_badge(venue)} · seat <b>{esc(b.seat_id)}</b></div>
    <div>Arrival: {b.start_time.strftime('%H:%M')} · booking <code>{esc(b.booking_id)}</code></div>
    {prepaid}
    <div class="birdie-muted" style="margin-top:6px">{esc(help_txt)}</div>
    <div style="margin-top:6px"><a href="{esc(url)}" target="_blank">Open the check-in link</a>
      <span class="birdie-muted">(same as scanning the QR)</span></div>
  </div>
</div>"""


def seat_choices(svc: BirdieService, venue_id: str) -> list[str]:
    return [ANY] + [s.seat_id for s in svc.bookings.available_seats(venue_id)]


def build_find_tab(svc: BirdieService, demo: gr.Blocks) -> None:
    venues = svc.venues()
    venue_choices = [(f"{v.name}{' (simulated)' if v.source.value == 'simulated' else ''}", v.venue_id) for v in venues]
    first = venues[0].venue_id
    all_zones = sorted({z for v in venues for z in v.zones})
    areas = sorted({v.area for v in venues} | {a.title() for a in AREA_COORDS})

    gr.Markdown(
        "Live free seats per venue and zone. **Only Nestwork Msheireb is live** (camera in the room); the other "
        "venues are **simulated** to show Birdie across Doha."
    )
    arrival = gr.Slider(0, 120, value=20, step=5, label="I'll arrive in (minutes)")
    cards = gr.HTML(venue_cards(svc, 20))

    with gr.Row():
        with gr.Column(scale=3):
            venue_dd = gr.Dropdown(choices=venue_choices, value=first, label="Venue")
        with gr.Column(scale=2):
            gr.Markdown("### Book a seat")
            seat_dd = gr.Dropdown(
                choices=seat_choices(svc, first), value=ANY, label="Optional seat (bookable and free now)"
            )
            book_btn = gr.Button("Book this seat", variant="primary")
            book_msg = gr.Markdown()
            booking_card = gr.HTML()
            cancel_btn = gr.Button("Cancel booking", visible=False)
            booking_state = gr.State(None)
            base_url_state = gr.State("")

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

    # --- handlers -------------------------------------------------------------------
    def refresh(arrival_min, venue_id, booking_id, base_url):
        return venue_cards(svc, int(arrival_min)), booking_html(svc, booking_id, base_url)

    gr.Timer(3.0).tick(refresh, [arrival, venue_dd, booking_state, base_url_state], [cards, booking_card],
                       show_progress="hidden")
    arrival.change(lambda a: venue_cards(svc, int(a)), [arrival], [cards], show_progress="hidden")

    def on_venue(venue_id):
        return gr.update(choices=seat_choices(svc, venue_id), value=ANY)

    venue_dd.change(on_venue, [venue_dd], [seat_dd])
    demo.load(lambda a: venue_cards(svc, int(a)), [arrival], [cards])
    seat_dd.focus(lambda v: gr.update(choices=seat_choices(svc, v)), [venue_dd], [seat_dd])

    def do_recommend(area_v, party_v, vtype_v, zone_v, outlet_v, quiet_v, arrival_min):
        q = Query(
            area=None if area_v in (None, "", ANY) else area_v,
            party_size=max(1, int(party_v or 1)),
            needs_outlet=bool(outlet_v),
            quiet=bool(quiet_v),
            zone=None if zone_v in (None, "", ANY) else zone_v,
            venue_type=None if vtype_v in (None, "", ANY) else VenueType(vtype_v),
            arrival_minutes=int(arrival_min),
        )
        return recommendations_html(recommend(svc, q), q)

    go.click(do_recommend, [area, party, vtype, zone, outlet, quiet, arrival], [results])

    def do_book(venue_id, seat_id, arrival_min, request: gr.Request):
        base = public_base_url(request)
        try:
            b = svc.bookings.book(venue_id, None if seat_id in (None, "", ANY) else seat_id,
                                  arrival_minutes=int(arrival_min))
        except BookingError as exc:
            return f"⚠️ {exc}", gr.skip(), gr.skip(), gr.skip(), base, gr.skip()
        return (
            f"Booked seat **{b.seat_id}**. Show this QR at the table, or scan the table's QR.",
            booking_html(svc, b.booking_id, base),
            b.booking_id,
            gr.update(visible=True),
            base,
            gr.update(choices=seat_choices(svc, venue_id), value=ANY),
        )

    book_btn.click(do_book, [venue_dd, seat_dd, arrival],
                   [book_msg, booking_card, booking_state, cancel_btn, base_url_state, seat_dd])

    def do_cancel(booking_id, base_url, venue_id):
        if not booking_id:
            return gr.skip(), gr.skip(), gr.skip()
        try:
            svc.bookings.cancel(booking_id)
            msg = "Booking cancelled."
        except BookingError as exc:
            msg = f"⚠️ {exc}"
        return msg, booking_html(svc, booking_id, base_url), gr.update(choices=seat_choices(svc, venue_id), value=ANY)

    cancel_btn.click(do_cancel, [booking_state, base_url_state, venue_dd], [book_msg, booking_card, seat_dd])
