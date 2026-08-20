"""Parser tests for WinTax HTML fixtures."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from custom_components.wintax.const import DEFAULT_TIMEZONE
from custom_components.wintax.parser import (
    extract_session_id,
    is_login_page,
    parse_rides,
    parse_tracking,
    select_relevant_ride,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def _at(day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=DEFAULT_TIMEZONE)


def test_login_page_detected() -> None:
    html = load_fixture("login.html")
    assert is_login_page(html)
    assert parse_rides(html) == []
    assert parse_tracking(html) is None


def test_normal_ride() -> None:
    rides = parse_rides(load_fixture("rides.html"))
    outbound = next(ride for ride in rides if ride.trip_id == "1001")
    assert outbound.ride_date.isoformat() == "2026-08-17"
    assert outbound.planned_start == _at(17, 7, 8)
    assert outbound.planned_end == _at(17, 8, 28)
    assert outbound.actual_start == _at(17, 7, 12)
    assert outbound.actual_end == _at(17, 8, 12)
    assert outbound.origin == "Voorbeeldstraat 1 (9999AA)"
    assert outbound.destination == "School Voorbeeld (9999BB)"
    assert outbound.passenger_count == 1
    assert outbound.status is None
    assert outbound.is_return is False
    assert outbound.is_composition is True
    assert outbound.tracking_available is False


def test_return_ride() -> None:
    rides = parse_rides(load_fixture("rides.html"))
    retour = next(ride for ride in rides if ride.trip_id == "1002")
    assert retour.is_return is True
    assert retour.origin == "School Voorbeeld (9999BB)"
    assert retour.destination == "Voorbeeldstraat 1 (9999AA)"
    assert retour.tracking_available is False


def test_active_ride_onderweg_naar_klant() -> None:
    rides = parse_rides(load_fixture("rides.html"))
    active = next(ride for ride in rides if ride.trip_id == "1003")
    assert active.status == "Onderweg naar klant"
    assert active.has_live_status is True
    assert active.is_return is True
    assert active.calculated_pickup == _at(20, 13, 48)
    assert active.is_active(_at(20, 14, 30)) is True


def test_ride_without_tracking() -> None:
    rides = parse_rides(load_fixture("rides.html"))
    ride = next(ride for ride in rides if ride.trip_id == "1004")
    assert ride.tracking_available is False
    assert ride.status == "Automatisch verzenden"
    assert ride.has_live_status is False


def test_ride_with_tracking() -> None:
    rides = parse_rides(load_fixture("rides.html"))
    ride = next(ride for ride in rides if ride.trip_id == "1003")
    assert ride.tracking_available is True


def test_multiple_rides() -> None:
    rides = parse_rides(load_fixture("rides.html"))
    assert [ride.trip_id for ride in rides] == ["1001", "1002", "1003", "1004", "1005"]


def test_no_rides() -> None:
    rides = parse_rides(load_fixture("no_rides.html"))
    assert rides == []
    assert select_relevant_ride(rides, _at(20, 12, 0)) is None


def test_malformed_and_missing_fields() -> None:
    rides = parse_rides(load_fixture("malformed.html"))
    assert len(rides) == 1
    ride = rides[0]
    assert ride.trip_id is None
    assert ride.planned_start == _at(25, 9, 0)
    assert ride.origin is None
    assert ride.destination is None
    assert ride.passenger_count is None


def test_select_active_over_upcoming() -> None:
    rides = parse_rides(load_fixture("rides.html"))
    selected = select_relevant_ride(rides, _at(20, 14, 10))
    assert selected is not None
    assert selected.trip_id == "1003"
    assert selected.status == "Onderweg naar klant"


def test_select_next_upcoming() -> None:
    rides = parse_rides(load_fixture("rides.html"))
    selected = select_relevant_ride(rides, _at(20, 16, 0))
    assert selected is not None
    assert selected.trip_id == "1004"


def test_select_most_recent() -> None:
    rides = parse_rides(load_fixture("rides.html"))
    selected = select_relevant_ride(rides, _at(31, 18, 0))
    assert selected is not None
    assert selected.trip_id == "1005"


def test_extract_session_id() -> None:
    html = load_fixture("rides.html")
    assert extract_session_id("https://example/client/index.wts?sessionid=abc123", html) == "abc123"
    assert extract_session_id(None, html) == "testsession"
    assert extract_session_id("https://example/client/index.wts", None) is None


def test_parse_tracking_with_gps() -> None:
    tracking = parse_tracking(load_fixture("map_with_gps.html"), trip_id="1003")
    assert tracking is not None
    assert tracking.has_coordinates is True
    assert tracking.latitude == pytest.approx(53.3312)
    assert tracking.longitude == pytest.approx(6.9084)
    assert tracking.trip_id == "1003"


def test_parse_tracking_without_gps() -> None:
    assert parse_tracking(load_fixture("map_without_gps.html")) is None
    assert parse_tracking("") is None
    assert parse_tracking("   ") is None


def test_parse_tracking_does_not_invent_zero_zero() -> None:
    html = "<script>L.marker([0, 0]).addTo(map);</script>"
    assert parse_tracking(html) is None


AUGUSTUS = Path.home() / "Downloads" / "augustus.html"


@pytest.mark.skipif(not AUGUSTUS.exists(), reason="local augustus.html not present")
def test_augustus_html_fixture() -> None:
    """Run the parser against the captured portal page when available locally."""
    html = AUGUSTUS.read_text(encoding="utf-8", errors="replace")
    rides = parse_rides(html)
    assert len(rides) == 22
    assert all(ride.trip_id and ride.trip_id.isdigit() for ride in rides)
    assert any(ride.is_return for ride in rides)
    assert any(ride.status == "Onderweg naar klant" for ride in rides)
    assert any(ride.status == "Automatisch verzenden" for ride in rides)
    assert any(ride.tracking_available for ride in rides)
    tracked = next(ride for ride in rides if ride.tracking_available)
    assert tracked.trip_id is not None
    assert extract_session_id(None, html) is None  # fixture session id is placeholder xxx
