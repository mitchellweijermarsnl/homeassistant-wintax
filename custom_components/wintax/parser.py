"""HTML parsers for the WinTax customer portal.

WinTax is a server-rendered .wts application. Ride data lives in HTML, not JSON.
Keep this module free of HTTP so it can be updated independently as more pages
are reverse-engineered.

The live map.wts response format is not fully known. parse_tracking() only
returns coordinates when they are clearly present; otherwise it returns None.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Iterable
from urllib.parse import parse_qs, urlparse
import logging
import re

from bs4 import BeautifulSoup, Tag

from .const import (
    ACTIVE_STATUS_KEYWORDS,
    DEFAULT_ACTIVE_GRACE_MINUTES,
    DEFAULT_TIMEZONE,
    METADATA_LABEL_PREFIXES,
    METADATA_LABELS,
)

_LOGGER = logging.getLogger(__name__)

_TIME_HEADER_RE = re.compile(
    r"(?P<date>\d{2}-\d{2}-\d{4})\s+(?P<start>\d{2}:\d{2})\s*-\s*(?P<end>\d{2}:\d{2})"
)
_TIME_RE = re.compile(r"(\d{2}:\d{2})")
_PAX_RE = re.compile(r"(\d+)\s*pax", re.IGNORECASE)
_TRIP_ID_IN_MAIL_RE = re.compile(r"Rit(?:%20|\s)+nummer(?:%20|\s)+(\d+)", re.IGNORECASE)
_SESSION_ID_RE = re.compile(
    r"(?:[?&]|&amp;)sessionid=([^&\"'#\s]+)", re.IGNORECASE
)
_DEST_META_RE = re.compile(r"\s*\(\d+\s*pax.*\)\s*$", re.IGNORECASE)

# Conservative GPS patterns. map.wts has not been fully reverse-engineered;
# these cover common mapping libraries that a tracking page might embed.
_COORD_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"L\.marker\(\s*\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]",
        re.IGNORECASE,
    ),
    re.compile(
        r"setView\(\s*\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:google\.maps\.)?LatLng\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)",
        re.IGNORECASE,
    ),
    re.compile(
        r"center\s*:\s*\{\s*lat\s*:\s*(-?\d+(?:\.\d+)?)\s*,\s*lng\s*:\s*(-?\d+(?:\.\d+)?)",
        re.IGNORECASE,
    ),
    re.compile(
        r'["\']lat(?:itude)?["\']\s*:\s*(-?\d+(?:\.\d+)?)\s*,\s*["\']l(?:ng|on|ongitude)["\']\s*:\s*(-?\d+(?:\.\d+)?)',
        re.IGNORECASE,
    ),
    re.compile(
        r"[?&](?:lat|latitude)=(-?\d+(?:\.\d+)?)[^\"'#]*[?&](?:lon|lng|longitude)=(-?\d+(?:\.\d+)?)",
        re.IGNORECASE,
    ),
    re.compile(
        r'data-lat=["\'](-?\d+(?:\.\d+)?)["\'][^>]*data-l(?:on|ng)=["\'](-?\d+(?:\.\d+)?)["\']',
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class Ride:
    """A single ride parsed from table#maintrips."""

    trip_id: str | None
    ride_date: date | None
    planned_start: datetime | None
    planned_end: datetime | None
    actual_start: datetime | None
    actual_end: datetime | None
    origin: str | None
    destination: str | None
    passenger_count: int | None
    status: str | None
    is_return: bool
    is_composition: bool
    tracking_available: bool
    calculated_pickup: datetime | None
    cancelled: bool

    @property
    def has_live_status(self) -> bool:
        """Return True when WinTax reports the vehicle is currently executing this ride."""
        if not self.status:
            return False
        lowered = self.status.casefold()
        return any(keyword in lowered for keyword in ACTIVE_STATUS_KEYWORDS)

    def is_active(
        self,
        now: datetime,
        *,
        grace_minutes: int = DEFAULT_ACTIVE_GRACE_MINUTES,
    ) -> bool:
        """Return True when this ride is currently in progress.

        Live status labels such as "Onderweg naar klant" only count on the
        ride's own date, and not longer than grace_minutes after the end.
        Otherwise a monthly HTML snapshot would keep an old in-progress ride
        selected.
        """
        if self.cancelled:
            return False
        start = self.actual_start or self.planned_start
        end = self.actual_end or self.planned_end

        if self.has_live_status:
            if self.ride_date is not None and self.ride_date != now.date():
                return False
            if end is not None and now > end + timedelta(minutes=grace_minutes):
                return False
            return True

        if start is None or end is None:
            return False
        return start <= now <= end


@dataclass(frozen=True)
class TrackingData:
    """Tracking information extracted from map.wts, if any GPS data is present."""

    trip_id: str | None
    latitude: float | None
    longitude: float | None
    status: str | None
    timestamp: datetime | None

    @property
    def has_coordinates(self) -> bool:
        """Return True when usable GPS coordinates were found."""
        return (
            self.latitude is not None
            and self.longitude is not None
            and _valid_coordinates(self.latitude, self.longitude)
        )


def parse_rides(html: str, *, tz: tzinfo | None = None) -> list[Ride]:
    """Parse rides from an authenticated WinTax index.wts HTML response."""
    timezone = tz or DEFAULT_TIMEZONE
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="maintrips")
    if table is None:
        _LOGGER.debug("WinTax rides page did not contain table#maintrips")
        return []

    rides: list[Ride] = []
    for row in table.find_all("tr"):
        ride = _parse_ride_row(row, timezone)
        if ride is not None:
            rides.append(ride)
    return rides


def parse_tracking(html: str, *, trip_id: str | None = None) -> TrackingData | None:
    """Parse tracking data from a map.wts response.

    Returns None when the page is a login form, empty, or contains no GPS data.
    Do not invent coordinates.
    """
    if not html or not html.strip():
        return None
    if is_login_page(html):
        return None

    latitude: float | None = None
    longitude: float | None = None

    for pattern in _COORD_PATTERNS:
        match = pattern.search(html)
        if match:
            try:
                latitude = float(match.group(1))
                longitude = float(match.group(2))
            except (TypeError, ValueError):
                continue
            if _valid_coordinates(latitude, longitude):
                break
            latitude = None
            longitude = None

    if latitude is None or longitude is None:
        lat_input, lon_input = _coordinates_from_inputs(html)
        if lat_input is not None and lon_input is not None:
            latitude, longitude = lat_input, lon_input

    if not _valid_coordinates(latitude, longitude):
        return None

    parsed_trip_id = trip_id or _trip_id_from_html(html)
    return TrackingData(
        trip_id=parsed_trip_id,
        latitude=latitude,
        longitude=longitude,
        status=_tracking_status_from_html(html),
        timestamp=None,
    )


def select_relevant_ride(
    rides: Iterable[Ride],
    now: datetime,
    *,
    grace_minutes: int = DEFAULT_ACTIVE_GRACE_MINUTES,
) -> Ride | None:
    """Pick the currently active ride, else the next upcoming, else the most recent."""
    candidates = [ride for ride in rides if not ride.cancelled]
    if not candidates:
        candidates = list(rides)
    if not candidates:
        return None

    timed = [ride for ride in candidates if ride.planned_start is not None]
    pool = timed or candidates

    active = [
        ride for ride in pool if ride.is_active(now, grace_minutes=grace_minutes)
    ]
    if active:
        live = [ride for ride in active if ride.has_live_status]
        return min(live or active, key=_start_sort_key)

    upcoming = [
        ride
        for ride in pool
        if ride.planned_start is not None and ride.planned_start > now
    ]
    if upcoming:
        return min(upcoming, key=_start_sort_key)

    past = [
        ride
        for ride in pool
        if (ride.actual_end or ride.planned_end or ride.planned_start) is not None
        and (ride.actual_end or ride.planned_end or ride.planned_start) <= now  # type: ignore[operator]
    ]
    if past:
        return max(past, key=_end_sort_key)

    return pool[0]


def is_login_page(html: str) -> bool:
    """Return True when the HTML is the WinTax login form rather than an authenticated page."""
    if not html:
        return False
    lowered = html.casefold()
    if "m=login_post" in lowered:
        return True
    if 'name="u"' in lowered and 'name="p"' in lowered and "inloggen" in lowered:
        return True
    return False


def is_authenticated_page(html: str) -> bool:
    """Return True when the HTML looks like an authenticated WinTax page."""
    if not html or is_login_page(html):
        return False
    lowered = html.casefold()
    return "m=logout" in lowered or 'id="maintrips"' in lowered


def extract_session_id(url: str | None, html: str | None = None) -> str | None:
    """Extract a WinTax sessionid from a URL and/or HTML body."""
    for source in (url, html):
        if not source:
            continue
        match = _SESSION_ID_RE.search(source)
        if match:
            value = match.group(1).strip()
            if value and value.lower() not in {"xxx", "none", "null"}:
                return value
        parsed = urlparse(source)
        values = parse_qs(parsed.query).get("sessionid") or []
        if values and values[0] and values[0].lower() not in {"xxx", "none", "null"}:
            return values[0]
    return None


def _parse_ride_row(row: Tag, timezone: tzinfo) -> Ride | None:
    cells = row.find_all("td", recursive=False)
    if not cells:
        # Some WinTax rows omit </td>; fall back to any td.
        cells = row.find_all("td")
    if not cells:
        return None

    first = cells[0]
    text = first.get_text(" ", strip=True)
    if not text:
        return None
    if text.casefold() in {"", "geannuleerd"}:
        return None

    header_match = _TIME_HEADER_RE.search(text)
    ride_date: date | None = None
    planned_start: datetime | None = None
    planned_end: datetime | None = None
    if header_match:
        ride_date = _parse_dutch_date(header_match.group("date"))
        planned_start = _combine(ride_date, header_match.group("start"), timezone)
        planned_end = _combine(ride_date, header_match.group("end"), timezone)
        if (
            planned_start is not None
            and planned_end is not None
            and planned_end < planned_start
        ):
            planned_end = planned_end + timedelta(days=1)

    labels = _label_texts(first)
    status = _status_from_labels(labels)
    is_return = any(label.casefold() == "retour" for label in labels)
    is_composition = any(label.casefold() == "samenstelling" for label in labels)
    actual_start = _datetime_from_prefixed_label(labels, "starttijd", ride_date, timezone)
    actual_end = _datetime_from_prefixed_label(labels, "eindtijd", ride_date, timezone)
    calculated_pickup = _datetime_from_prefixed_label(
        labels, "berekende voorrijtijd", ride_date, timezone
    )

    origin, destination = _parse_route(first)
    passenger_count = _parse_passenger_count(text)
    trip_id = _trip_id_from_row(row)
    tracking_available = _has_tracking_link(first)
    cancelled = _is_cancelled(row)

    # A row without a time header and without a trip id is almost certainly
    # the "Bijwerken" action row, not a ride.
    if header_match is None and trip_id is None:
        return None

    return Ride(
        trip_id=trip_id,
        ride_date=ride_date,
        planned_start=planned_start,
        planned_end=planned_end,
        actual_start=actual_start,
        actual_end=actual_end,
        origin=origin,
        destination=destination,
        passenger_count=passenger_count,
        status=status,
        is_return=is_return,
        is_composition=is_composition,
        tracking_available=tracking_available,
        calculated_pickup=calculated_pickup,
        cancelled=cancelled,
    )


def _label_texts(cell: Tag) -> list[str]:
    labels: list[str] = []
    for span in cell.select("div.pull-right span.label"):
        label = span.get_text(" ", strip=True)
        if label:
            labels.append(label)
    return labels


def _status_from_labels(labels: list[str]) -> str | None:
    """Return the WinTax status label, ignoring metadata chips."""
    for label in labels:
        lowered = label.casefold()
        if lowered in METADATA_LABELS:
            continue
        if any(lowered.startswith(prefix) for prefix in METADATA_LABEL_PREFIXES):
            continue
        return label
    return None


def _datetime_from_prefixed_label(
    labels: list[str],
    prefix: str,
    ride_date: date | None,
    timezone: tzinfo,
) -> datetime | None:
    prefix_cf = prefix.casefold()
    for label in labels:
        lowered = label.casefold()
        if not lowered.startswith(prefix_cf):
            continue
        match = _TIME_RE.search(label)
        if not match:
            return None
        return _combine(ride_date, match.group(1), timezone)
    return None


def _parse_route(cell: Tag) -> tuple[str | None, str | None]:
    arrow = cell.find("i", class_=lambda value: value and "icon-arrow-right" in value)
    if arrow is None:
        return None, None

    origin_bits: list[str] = []
    for sibling in arrow.previous_siblings:
        name = getattr(sibling, "name", None)
        if name in {"br", "div", "ul"}:
            break
        origin_bits.append(_node_text(sibling))
    origin = _clean_space("".join(reversed(origin_bits))) or None

    dest_bits: list[str] = []
    for sibling in arrow.next_siblings:
        name = getattr(sibling, "name", None)
        if name in {"ul", "div"}:
            break
        dest_bits.append(_node_text(sibling))
    destination = _clean_space("".join(dest_bits)) or None
    if destination:
        destination = _DEST_META_RE.sub("", destination).strip() or destination

    return origin, destination or None


def _parse_passenger_count(text: str) -> int | None:
    match = _PAX_RE.search(text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _trip_id_from_row(row: Tag) -> str | None:
    cancel = row.find("input", attrs={"name": re.compile(r"^cancel$", re.I)})
    if cancel is not None:
        value = cancel.get("value")
        if value and str(value).isdigit():
            return str(value)

    for link in row.find_all("a", href=True):
        href = link["href"]
        parsed = urlparse(href)
        values = parse_qs(parsed.query).get("tripid") or []
        if values and values[0].isdigit():
            return values[0]
        match = _TRIP_ID_IN_MAIL_RE.search(href)
        if match:
            return match.group(1)
    return None


def _has_tracking_link(cell: Tag) -> bool:
    for link in cell.find_all("a", href=True):
        href = link["href"].casefold()
        if "map.wts" in href and "tripid=" in href:
            return True
        if "tracking" in link.get_text(" ", strip=True).casefold():
            return True
    return False


def _is_cancelled(row: Tag) -> bool:
    cancel = row.find("input", attrs={"name": re.compile(r"^cancel$", re.I)})
    if cancel is None:
        return False
    return cancel.has_attr("checked")


def _trip_id_from_html(html: str) -> str | None:
    parsed = urlparse(html if "tripid=" in html else "")
    values = parse_qs(parsed.query).get("tripid") or []
    if values:
        return values[0]
    match = re.search(r"[?&]tripid=(\d+)", html, re.IGNORECASE)
    return match.group(1) if match else None


def _tracking_status_from_html(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for span in soup.select("span.label"):
        label = span.get_text(" ", strip=True)
        if not label:
            continue
        lowered = label.casefold()
        if lowered in METADATA_LABELS:
            continue
        if any(lowered.startswith(prefix) for prefix in METADATA_LABEL_PREFIXES):
            continue
        return label
    return None


def _coordinates_from_inputs(html: str) -> tuple[float | None, float | None]:
    soup = BeautifulSoup(html, "html.parser")
    lat_el = soup.find("input", attrs={"name": re.compile(r"^lat(?:itude)?$", re.I)})
    lon_el = soup.find(
        "input", attrs={"name": re.compile(r"^(?:lon|lng|longitude)$", re.I)}
    )
    if lat_el is None or lon_el is None:
        return None, None
    try:
        latitude = float(str(lat_el.get("value", "")).strip())
        longitude = float(str(lon_el.get("value", "")).strip())
    except ValueError:
        return None, None
    if _valid_coordinates(latitude, longitude):
        return latitude, longitude
    return None, None


def _parse_dutch_date(value: str) -> date | None:
    try:
        day, month, year = value.split("-")
        return date(int(year), int(month), int(day))
    except (TypeError, ValueError):
        return None


def _combine(
    ride_date: date | None, clock: str | None, timezone: tzinfo
) -> datetime | None:
    if ride_date is None or not clock:
        return None
    try:
        hours, minutes = clock.split(":")
        parsed_time = time(int(hours), int(minutes), tzinfo=timezone)
        return datetime.combine(ride_date, parsed_time)
    except (TypeError, ValueError):
        return None


def _valid_coordinates(latitude: float | None, longitude: float | None) -> bool:
    if latitude is None or longitude is None:
        return False
    if latitude == 0.0 and longitude == 0.0:
        return False
    return -90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0


def _start_sort_key(ride: Ride) -> datetime:
    return ride.planned_start or datetime.min.replace(tzinfo=DEFAULT_TIMEZONE)


def _end_sort_key(ride: Ride) -> datetime:
    return (
        ride.actual_end
        or ride.planned_end
        or ride.planned_start
        or datetime.min.replace(tzinfo=DEFAULT_TIMEZONE)
    )


def _node_text(node: object) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, Tag):
        if node.name == "i":
            return ""
        return node.get_text(" ", strip=False)
    return ""


def _clean_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
