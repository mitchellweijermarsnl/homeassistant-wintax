"""Home circle and distance helpers.

Kept free of Home Assistant so the radius check can be tested on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from typing import Any

from .const import (
    CONF_HOME,
    DEFAULT_HOME_RADIUS_METERS,
    MAX_HOME_RADIUS_METERS,
    MIN_HOME_RADIUS_METERS,
)

_EARTH_RADIUS_METERS = 6_371_000.0


@dataclass(frozen=True)
class HomeTarget:
    """Point and radius that count as near home."""

    latitude: float
    longitude: float
    radius: float


def distance_meters(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Return the great-circle distance between two WGS84 points, in meters."""
    phi_a = radians(latitude_a)
    phi_b = radians(latitude_b)
    delta_phi = radians(latitude_b - latitude_a)
    delta_lambda = radians(longitude_b - longitude_a)
    haversine = (
        sin(delta_phi / 2) ** 2
        + cos(phi_a) * cos(phi_b) * sin(delta_lambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_METERS * asin(sqrt(haversine))


def within_radius(
    home_latitude: float,
    home_longitude: float,
    latitude: float,
    longitude: float,
    radius: float,
) -> bool:
    """Return True when the point lies inside or on the circle."""
    return (
        distance_meters(home_latitude, home_longitude, latitude, longitude) <= radius
    )


def validate_home(value: Any) -> tuple[HomeTarget | None, str | None]:
    """Validate a location-selector value.

    Returns the target, or an options-flow error key when the value cannot be
    stored.
    """
    if not isinstance(value, dict):
        return None, "invalid_location"
    try:
        latitude = float(value["latitude"])
        longitude = float(value["longitude"])
    except (KeyError, TypeError, ValueError):
        return None, "invalid_location"
    if not _valid_coordinates(latitude, longitude):
        return None, "invalid_location"
    try:
        radius = float(value["radius"])
    except (KeyError, TypeError, ValueError):
        return None, "invalid_radius"
    if not MIN_HOME_RADIUS_METERS <= radius <= MAX_HOME_RADIUS_METERS:
        return None, "invalid_radius"
    return HomeTarget(latitude=latitude, longitude=longitude, radius=radius), None


def parse_home_option(value: Any) -> HomeTarget | None:
    """Return a stored home circle, or None when it is missing or invalid."""
    target, error = validate_home(value)
    if error is not None:
        return None
    return target


def resolve_home(
    options: dict[str, Any],
    *,
    fallback_latitude: float | None,
    fallback_longitude: float | None,
    fallback_radius: float | None,
) -> HomeTarget | None:
    """Use the saved circle, otherwise the Home Assistant home zone."""
    stored = parse_home_option(options.get(CONF_HOME))
    if stored is not None:
        return stored
    if fallback_latitude is None or fallback_longitude is None:
        return None
    if not _valid_coordinates(fallback_latitude, fallback_longitude):
        return None
    radius = DEFAULT_HOME_RADIUS_METERS
    if isinstance(fallback_radius, (int, float)) and not isinstance(fallback_radius, bool):
        if fallback_radius > 0:
            radius = float(fallback_radius)
    radius = min(max(radius, MIN_HOME_RADIUS_METERS), MAX_HOME_RADIUS_METERS)
    return HomeTarget(
        latitude=float(fallback_latitude),
        longitude=float(fallback_longitude),
        radius=radius,
    )


def suggested_home(
    *,
    latitude: float | None,
    longitude: float | None,
    radius: float | None,
) -> dict[str, float]:
    """Default map pin for the options form."""
    target = resolve_home(
        {},
        fallback_latitude=latitude,
        fallback_longitude=longitude,
        fallback_radius=radius,
    )
    if target is None:
        return {
            "latitude": float(latitude or 0.0),
            "longitude": float(longitude or 0.0),
            "radius": float(DEFAULT_HOME_RADIUS_METERS),
        }
    return {
        "latitude": target.latitude,
        "longitude": target.longitude,
        "radius": target.radius,
    }


def _valid_coordinates(latitude: float, longitude: float) -> bool:
    if latitude == 0.0 and longitude == 0.0:
        return False
    return -90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0
