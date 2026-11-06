"""Verified booking (CLAUDE.md section 8.2).

BOOKED_PENDING -> (user scans the table QR, ?checkin=<booking_id>) -> QR_SCANNED
  -> (camera or simulator sees the seat OCCUPIED within the confirmation window) -> CHECKED_IN
  -> (seat goes FREE, or the booking duration ends) -> COMPLETED
Still not occupied after the no-show time -> NO_SHOW_RELEASED (the seat goes back to walk-ins).

The camera never identifies who sits down: it only confirms that the booked seat is occupied.
"""

from __future__ import annotations

import io
import threading
import uuid
from collections.abc import Callable, Mapping
from datetime import timedelta
from urllib.parse import urlencode

from birdie.clock import Clock
from birdie.config import CAFE_PREPAID_ITEM, TIMERS, Timers
from birdie.models import (
    ACTIVE_BOOKING_STATUSES,
    Booking,
    BookingStatus,
    Seat,
    SeatEvent,
    SeatSnapshot,
    SeatState,
    VenueConfig,
    VenueType,
)
from birdie.storage import Repository

PENDING_STATUSES = frozenset({BookingStatus.BOOKED_PENDING, BookingStatus.QR_SCANNED})
TERMINAL_MESSAGES = {
    BookingStatus.COMPLETED: "This booking is already completed.",
    BookingStatus.NO_SHOW_RELEASED: "This booking was released to walk-ins because nobody arrived in time.",
    BookingStatus.CANCELLED: "This booking was cancelled.",
}


class BookingError(ValueError):
    """A booking rule was broken. The message is safe to show to users."""


def max_active_bookings(n_seats: int, bookable_fraction: float) -> int:
    """At most `bookable_fraction` of a venue's seats can be booked at the same time."""
    return int(n_seats * bookable_fraction + 1e-9)


def checkin_url(base_url: str, booking_id: str) -> str:
    """The URL printed in the table's QR code."""
    return f"{base_url.rstrip('/')}/?{urlencode({'checkin': booking_id})}"


def make_qr_png(data: str) -> bytes:
    """A QR code as PNG bytes (in memory)."""
    import qrcode

    img = qrcode.make(data, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def held_too_long(snapshots: list[SeatSnapshot], now, threshold_seconds: float) -> list[SeatSnapshot]:
    """Seats that have been HELD by belongings for at least the staff alert threshold."""
    limit = timedelta(seconds=threshold_seconds)
    return [s for s in snapshots if s.state == SeatState.HELD and now - s.since >= limit]


class BookingService:
    def __init__(
        self,
        repo: Repository,
        clock: Clock,
        configs: Mapping[str, VenueConfig],
        seat_state: Callable[[str, str], SeatState | None],
        timers: Timers = TIMERS,
    ) -> None:
        self.repo = repo
        self.clock = clock
        self.configs = configs  # shared with the service, so seat edits are seen here
        self.seat_state = seat_state
        self.timers = timers
        self._lock = threading.RLock()
        self._listeners: list[Callable[[Booking, BookingStatus | None], None]] = []
        self._alerted_unverified: set[str] = set()

    # --- queries ----------------------------------------------------------------
    def add_listener(self, fn: Callable[[Booking, BookingStatus | None], None]) -> None:
        """fn(booking, old_status) is called after every status change."""
        self._listeners.append(fn)

    def get(self, booking_id: str) -> Booking | None:
        return self.repo.get_booking(booking_id)

    def active_bookings(self, venue_id: str | None = None) -> list[Booking]:
        return self.repo.bookings(venue_id, ACTIVE_BOOKING_STATUSES)

    def active_booking_for_seat(self, venue_id: str, seat_id: str) -> Booking | None:
        return next((b for b in self.active_bookings(venue_id) if b.seat_id == seat_id), None)

    def bookable_seats(self, venue_id: str) -> list[Seat]:
        """Seats the venue marked as bookable."""
        return [s for s in self.configs[venue_id].seats if s.bookable]

    def booking_capacity(self, venue_id: str) -> int:
        cfg = self.configs[venue_id]
        return max_active_bookings(len(cfg.seats), cfg.venue.bookable_fraction)

    def available_seats(self, venue_id: str, zone: str | None = None, needs_outlet: bool = False) -> list[Seat]:
        """Bookable seats that are FREE now and not already booked."""
        if len(self.active_bookings(venue_id)) >= self.booking_capacity(venue_id):
            return []
        booked = {b.seat_id for b in self.active_bookings(venue_id)}
        out = []
        for s in self.bookable_seats(venue_id):
            if s.seat_id in booked or self.seat_state(venue_id, s.seat_id) != SeatState.FREE:
                continue
            if zone and s.zone != zone:
                continue
            if needs_outlet and not s.has_outlet:
                continue
            out.append(s)
        return out

    # --- commands --------------------------------------------------------------
    def book(
        self,
        venue_id: str,
        seat_id: str | None = None,
        arrival_minutes: int = 0,
        zone: str | None = None,
        needs_outlet: bool = False,
    ) -> Booking:
        """Book a seat for an arrival time. With no seat_id, the first available bookable seat is used."""
        with self._lock:
            cfg = self.configs.get(venue_id)
            if cfg is None:
                raise BookingError(f"Unknown venue: {venue_id}")
            active = self.active_bookings(venue_id)
            if len(active) >= self.booking_capacity(venue_id):
                raise BookingError(
                    f"{cfg.venue.name} only takes bookings for {int(cfg.venue.bookable_fraction * 100)}% of its seats, "
                    "and they are all booked. The rest are kept for walk-ins."
                )
            if seat_id is None:
                options = self.available_seats(venue_id, zone=zone, needs_outlet=needs_outlet)
                if not options:
                    raise BookingError("No bookable seat is free right now with those options.")
                seat = options[0]
            else:
                seat = next((s for s in cfg.seats if s.seat_id == seat_id), None)
                if seat is None:
                    raise BookingError(f"Unknown seat: {seat_id}")
                if not seat.bookable:
                    raise BookingError(f"Seat {seat_id} is kept for walk-ins and can't be booked.")
                if any(b.seat_id == seat_id for b in active):
                    raise BookingError(f"Seat {seat_id} is already booked.")
                if self.seat_state(venue_id, seat_id) != SeatState.FREE:
                    raise BookingError(f"Seat {seat_id} is taken right now.")
            now = self.clock.now()
            booking = Booking(
                booking_id=uuid.uuid4().hex[:10],
                venue_id=venue_id,
                seat_id=seat.seat_id,
                start_time=now + timedelta(minutes=max(0, arrival_minutes)),
                status=BookingStatus.BOOKED_PENDING,
                created_at=now,
                prepaid_item=CAFE_PREPAID_ITEM if cfg.venue.type == VenueType.cafe else None,
            )
            self.repo.save_booking(booking)
            self._log(booking, None)
            return booking

    def scan_qr(self, booking_id: str) -> Booking:
        """The user scanned the table's QR code (?checkin=<booking_id>)."""
        with self._lock:
            booking = self.get(booking_id)
            if booking is None:
                raise BookingError("Unknown booking. Check the QR code.")
            if booking.status in TERMINAL_MESSAGES:
                raise BookingError(TERMINAL_MESSAGES[booking.status])
            if booking.status == BookingStatus.BOOKED_PENDING:
                booking = self._set(booking, BookingStatus.QR_SCANNED)
            return self._try_confirm(booking)

    def cancel(self, booking_id: str) -> Booking:
        with self._lock:
            booking = self.get(booking_id)
            if booking is None:
                raise BookingError("Unknown booking.")
            if booking.status not in ACTIVE_BOOKING_STATUSES:
                raise BookingError(TERMINAL_MESSAGES.get(booking.status, "This booking can't be cancelled."))
            return self._set(booking, BookingStatus.CANCELLED)

    def on_seat_event(self, event: SeatEvent) -> None:
        """Called for every seat state change (camera or simulator)."""
        with self._lock:
            booking = self.active_booking_for_seat(event.venue_id, event.seat_id)
            if booking is None:
                return
            if booking.status == BookingStatus.QR_SCANNED and event.new_state == SeatState.OCCUPIED:
                self._try_confirm(booking)
            elif booking.status == BookingStatus.CHECKED_IN and event.new_state == SeatState.FREE:
                self._set(booking, BookingStatus.COMPLETED)

    def tick(self) -> list[Booking]:
        """No-show releases, check-in confirmation, completions. Run every couple of seconds."""
        changed = []
        now = self.clock.now()
        with self._lock:
            for booking in self.active_bookings():
                state = self.seat_state(booking.venue_id, booking.seat_id)
                if state is None:  # the seat was deleted
                    changed.append(self._set(booking, BookingStatus.CANCELLED))
                    continue
                new = self._next_status(booking, state, now)
                if new is not None:
                    changed.append(self._set(booking, new))
        return changed

    # --- internals --------------------------------------------------------------
    def _next_status(self, booking: Booking, state: SeatState, now) -> BookingStatus | None:
        t = self.timers
        if booking.status == BookingStatus.BOOKED_PENDING:
            if now >= booking.start_time + timedelta(seconds=t.no_show_seconds):
                if state == SeatState.FREE:
                    return BookingStatus.NO_SHOW_RELEASED
                # Occupied, but nobody scanned the QR: keep the booking and tell staff once.
                if booking.booking_id not in self._alerted_unverified:
                    self._alerted_unverified.add(booking.booking_id)
                    self.repo.add_alert(
                        now, booking.venue_id, booking.seat_id, "unverified_occupant",
                        f"Booked seat {booking.seat_id} is occupied but nobody scanned its QR code.",
                    )
            return None
        if booking.status == BookingStatus.QR_SCANNED:
            scanned_at = self.repo.status_since(booking.booking_id, BookingStatus.QR_SCANNED) or now
            if state == SeatState.OCCUPIED and now <= scanned_at + timedelta(seconds=t.checkin_window_seconds):
                return BookingStatus.CHECKED_IN
            if now > scanned_at + timedelta(seconds=t.checkin_window_seconds):
                return BookingStatus.NO_SHOW_RELEASED
            return None
        if booking.status == BookingStatus.CHECKED_IN:
            checked_in_at = self.repo.status_since(booking.booking_id, BookingStatus.CHECKED_IN) or now
            if state == SeatState.FREE or now >= checked_in_at + timedelta(seconds=t.booking_duration_seconds):
                return BookingStatus.COMPLETED
        return None

    def _try_confirm(self, booking: Booking) -> Booking:
        if booking.status != BookingStatus.QR_SCANNED:
            return booking
        now = self.clock.now()
        scanned_at = self.repo.status_since(booking.booking_id, BookingStatus.QR_SCANNED) or now
        within = now <= scanned_at + timedelta(seconds=self.timers.checkin_window_seconds)
        if within and self.seat_state(booking.venue_id, booking.seat_id) == SeatState.OCCUPIED:
            return self._set(booking, BookingStatus.CHECKED_IN)
        return booking

    def _set(self, booking: Booking, status: BookingStatus) -> Booking:
        old = booking.status
        updated = booking.model_copy(update={"status": status})
        self.repo.save_booking(updated)
        self._log(updated, old)
        return updated

    def _log(self, booking: Booking, old: BookingStatus | None) -> None:
        self.repo.add_booking_event(self.clock.now(), booking, old, booking.status)
        for fn in self._listeners:
            fn(booking, old)
