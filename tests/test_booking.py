import pytest

from birdie.booking import BookingError, checkin_url, make_qr_png, max_active_bookings
from birdie.config import CAFE_PREPAID_ITEM, DEMO_TIMERS
from birdie.models import BookingStatus, Seat, SeatState, Venue, VenueConfig, VenueSource, VenueType
from birdie.service import BirdieService
from birdie.storage import Repository
from birdie.vision.state import Observation

T = DEMO_TIMERS  # 60 s no-show, 60 s check-in window, 3-frame smoothing


def make_service(clock, venue_type=VenueType.cafe, n=10, bookable=(0, 1, 2), fraction=0.2):
    seats = [
        Seat(seat_id=f"S{i}", venue_id="v", zone="indoor", has_outlet=i % 2 == 0, bookable=i in bookable,
             polygon=[(0, 0), (0.1, 0), (0.1, 0.1)])
        for i in range(n)
    ]
    cfg = VenueConfig(
        venue=Venue(venue_id="v", name="Cafe V", area="Lusail", type=venue_type, lat=0, lon=0, zones=["indoor"],
                    bookable_fraction=fraction, source=VenueSource.live),
        seats=seats,
    )
    svc = BirdieService(repo=Repository(":memory:"), clock=clock, venues={"v": cfg}, timers=T,
                        detector=lambda *a, **k: [], persist_venues=False)
    tracker = svc.trackers["v"]
    tracker.stale_seconds = None
    for machine in tracker.machines.values():
        machine.stale = None
    tracker.force({seat.seat_id: SeatState.FREE for seat in seats})
    return svc


def sit(svc, clock, seat_id, obs=Observation.PERSON):
    """Feed k frames where `seat_id` has `obs` (all other seats keep their state)."""
    tracker = svc.trackers["v"]
    for _ in range(T.smoothing_frames):
        clock.advance(1)
        current = {sid: {SeatState.UNKNOWN: Observation.UNKNOWN, SeatState.FREE: Observation.EMPTY,
                         SeatState.OCCUPIED: Observation.PERSON, SeatState.HELD: Observation.ITEMS}[m.state]
                   for sid, m in tracker.machines.items()}
        current[seat_id] = obs
        tracker.process(current)


def statuses(svc, booking_id):
    return [e["new_status"] for e in svc.repo.booking_events() if e["booking_id"] == booking_id]


def test_capacity_is_bookable_fraction_of_seats():
    assert max_active_bookings(10, 0.2) == 2
    assert max_active_bookings(48, 0.25) == 12
    assert max_active_bookings(3, 0.2) == 0


def test_only_bookable_seats_and_fraction_limit(clock):
    svc = make_service(clock)
    with pytest.raises(BookingError, match="walk-ins"):
        svc.bookings.book("v", "S5")  # not bookable
    b1 = svc.bookings.book("v", "S0")
    with pytest.raises(BookingError, match="already booked"):
        svc.bookings.book("v", "S0")
    svc.bookings.book("v", "S1")
    with pytest.raises(BookingError, match="20%"):
        svc.bookings.book("v", "S2")  # capacity 2 of 10 seats reached
    assert b1.prepaid_item == CAFE_PREPAID_ITEM
    assert b1.status == BookingStatus.BOOKED_PENDING


def test_cannot_book_a_taken_seat(clock):
    svc = make_service(clock)
    sit(svc, clock, "S0")
    with pytest.raises(BookingError, match="taken"):
        svc.bookings.book("v", "S0")
    b = svc.bookings.book("v")  # auto-pick skips the taken seat
    assert b.seat_id == "S1"


def test_library_bookings_have_no_prepaid_item(clock):
    svc = make_service(clock, venue_type=VenueType.library)
    assert svc.bookings.book("v", "S0").prepaid_item is None


def test_qr_then_occupied_gives_checked_in(clock):
    svc = make_service(clock)
    b = svc.bookings.book("v", "S0")
    clock.advance(10)
    b = svc.bookings.scan_qr(b.booking_id)
    assert b.status == BookingStatus.QR_SCANNED  # camera hasn't seen anyone yet
    sit(svc, clock, "S0")
    assert svc.bookings.get(b.booking_id).status == BookingStatus.CHECKED_IN
    assert statuses(svc, b.booking_id) == ["BOOKED_PENDING", "QR_SCANNED", "CHECKED_IN"]


def test_already_seated_then_scan_checks_in_immediately(clock):
    svc = make_service(clock)
    b = svc.bookings.book("v", "S0")
    sit(svc, clock, "S0")
    assert svc.bookings.get(b.booking_id).status == BookingStatus.BOOKED_PENDING  # no QR yet
    assert svc.bookings.scan_qr(b.booking_id).status == BookingStatus.CHECKED_IN


def test_occupied_without_qr_is_not_checked_in(clock):
    svc = make_service(clock)
    b = svc.bookings.book("v", "S0")
    sit(svc, clock, "S0")
    svc.tick()
    assert svc.bookings.get(b.booking_id).status == BookingStatus.BOOKED_PENDING


def test_no_show_release_after_no_show_time(clock):
    svc = make_service(clock)
    b = svc.bookings.book("v", "S0", arrival_minutes=0)
    clock.advance(T.no_show_seconds - 1)
    svc.tick()
    assert svc.bookings.get(b.booking_id).status == BookingStatus.BOOKED_PENDING
    clock.advance(2)
    svc.tick()
    assert svc.bookings.get(b.booking_id).status == BookingStatus.NO_SHOW_RELEASED
    # The seat goes back to walk-ins: it can be booked again.
    assert svc.bookings.book("v", "S0").status == BookingStatus.BOOKED_PENDING


def test_no_show_counts_from_arrival_time(clock):
    svc = make_service(clock)
    b = svc.bookings.book("v", "S0", arrival_minutes=10)
    clock.advance(minutes=10, seconds=T.no_show_seconds - 5)
    svc.tick()
    assert svc.bookings.get(b.booking_id).status == BookingStatus.BOOKED_PENDING
    clock.advance(10)
    svc.tick()
    assert svc.bookings.get(b.booking_id).status == BookingStatus.NO_SHOW_RELEASED


def test_occupied_at_deadline_without_qr_alerts_staff_instead_of_releasing(clock):
    svc = make_service(clock)
    b = svc.bookings.book("v", "S0")
    sit(svc, clock, "S0")
    clock.advance(T.no_show_seconds + 1)
    svc.tick()
    svc.tick()
    assert svc.bookings.get(b.booking_id).status == BookingStatus.BOOKED_PENDING
    alerts = [a for a in svc.repo.alerts("v") if a["kind"] == "unverified_occupant"]
    assert len(alerts) == 1


def test_qr_scanned_but_seat_never_occupied_is_released(clock):
    svc = make_service(clock)
    b = svc.bookings.book("v", "S0")
    svc.bookings.scan_qr(b.booking_id)
    clock.advance(T.checkin_window_seconds + 1)
    svc.tick()
    assert svc.bookings.get(b.booking_id).status == BookingStatus.NO_SHOW_RELEASED
    with pytest.raises(BookingError, match="released"):
        svc.bookings.scan_qr(b.booking_id)


def test_unknown_camera_does_not_mark_qr_booking_as_no_show(clock):
    svc = make_service(clock)
    b = svc.bookings.book("v", "S0")
    svc.bookings.scan_qr(b.booking_id)
    svc.trackers["v"].process({"S0": Observation.UNKNOWN})
    clock.advance(T.checkin_window_seconds + 1)
    svc.tick()
    assert svc.bookings.get(b.booking_id).status == BookingStatus.QR_SCANNED


def test_checked_in_completes_when_seat_freed(clock):
    svc = make_service(clock)
    b = svc.bookings.book("v", "S0")
    svc.bookings.scan_qr(b.booking_id)
    sit(svc, clock, "S0")
    sit(svc, clock, "S0", Observation.EMPTY)
    assert svc.bookings.get(b.booking_id).status == BookingStatus.COMPLETED


def test_checked_in_completes_after_duration(clock):
    svc = make_service(clock)
    b = svc.bookings.book("v", "S0")
    svc.bookings.scan_qr(b.booking_id)
    sit(svc, clock, "S0")
    clock.advance(T.booking_duration_seconds + 1)
    svc.tick()
    assert svc.bookings.get(b.booking_id).status == BookingStatus.COMPLETED


def test_cancel(clock):
    svc = make_service(clock)
    b = svc.bookings.book("v", "S0")
    assert svc.bookings.cancel(b.booking_id).status == BookingStatus.CANCELLED
    with pytest.raises(BookingError):
        svc.bookings.cancel(b.booking_id)


def test_held_too_long_raises_one_staff_alert_and_resolves(clock):
    svc = make_service(clock)
    sit(svc, clock, "S3", Observation.ITEMS)
    clock.advance(T.hold_seconds)
    svc.tick()
    assert svc.state_of("v", "S3") == SeatState.HELD
    clock.advance(T.staff_alert_seconds)
    svc.tick()
    svc.tick()
    alerts = svc.repo.alerts("v", unresolved_only=True)
    assert [a["kind"] for a in alerts] == ["held_too_long"]
    svc.trackers["v"].process({"S3": Observation.UNKNOWN})
    assert len(svc.repo.alerts("v", unresolved_only=True)) == 1
    sit(svc, clock, "S3", Observation.EMPTY)  # staff cleared the seat
    assert svc.repo.alerts("v", unresolved_only=True) == []


def test_qr_code_and_checkin_url():
    url = checkin_url("https://user-birdie.hf.space/", "abc123")
    assert url == "https://user-birdie.hf.space/?checkin=abc123"
    png = make_qr_png(url)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_scheduler_records_occupancy(clock):
    svc = make_service(clock)
    sit(svc, clock, "S0")
    svc.tick()
    [bucket] = svc.repo.occupancy_buckets("v")
    assert bucket["occupied"] == 1 and bucket["free"] == 9


def test_scheduler_thread_starts_and_stops(clock):
    svc = make_service(clock)
    svc.scheduler.interval = 0.01
    svc.start()
    assert svc.scheduler.running
    svc.stop()
    assert not svc.scheduler.running
