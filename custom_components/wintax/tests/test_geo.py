"""Tests for the home circle and distance helpers."""

from __future__ import annotations

import pytest

from custom_components.wintax.const import CONF_HOME
from custom_components.wintax.geo import (
    distance_meters,
    resolve_home,
    suggested_home,
    validate_home,
    within_radius,
)


def test_distance_same_point_is_zero() -> None:
    assert distance_meters(52.0, 5.0, 52.0, 5.0) == 0.0


def test_distance_due_north() -> None:
    # 0.001 degree of latitude is about 111.2 m on the mean Earth radius.
    assert distance_meters(52.0, 5.0, 52.001, 5.0) == pytest.approx(111.195, abs=0.01)


def test_within_radius_includes_the_boundary() -> None:
    distance = distance_meters(52.37, 4.89, 52.371, 4.89)
    assert within_radius(52.37, 4.89, 52.371, 4.89, distance) is True
    assert within_radius(52.37, 4.89, 52.371, 4.89, distance - 1) is False


def test_validate_home_accepts_a_circle() -> None:
    target, error = validate_home(
        {"latitude": 52.37, "longitude": 4.89, "radius": 250}
    )
    assert error is None
    assert target is not None
    assert target.radius == 250


def test_validate_home_rejects_missing_point_and_bad_radius() -> None:
    assert validate_home("nope")[1] == "invalid_location"
    assert validate_home({"longitude": 4.89, "radius": 100})[1] == "invalid_location"
    assert validate_home({"latitude": 0, "longitude": 0, "radius": 100})[1] == (
        "invalid_location"
    )
    assert validate_home({"latitude": 52.37, "longitude": 4.89})[1] == "invalid_radius"
    assert validate_home({"latitude": 52.37, "longitude": 4.89, "radius": 9})[1] == (
        "invalid_radius"
    )
    assert validate_home(
        {"latitude": 52.37, "longitude": 4.89, "radius": 20001}
    )[1] == "invalid_radius"
    low, low_error = validate_home(
        {"latitude": 52.37, "longitude": 4.89, "radius": 10}
    )
    high, high_error = validate_home(
        {"latitude": 52.37, "longitude": 4.89, "radius": 20000}
    )
    assert low_error is None and low is not None
    assert high_error is None and high is not None


def test_resolve_home_prefers_the_saved_circle() -> None:
    target = resolve_home(
        {CONF_HOME: {"latitude": 51.0, "longitude": 6.0, "radius": 400}},
        fallback_latitude=52.0,
        fallback_longitude=5.0,
        fallback_radius=100,
    )
    assert target is not None
    assert target.latitude == 51.0
    assert target.radius == 400


def test_resolve_home_falls_back_to_the_zone() -> None:
    target = resolve_home(
        {},
        fallback_latitude=52.1,
        fallback_longitude=5.1,
        fallback_radius=180,
    )
    assert target is not None
    assert (target.latitude, target.longitude, target.radius) == (52.1, 5.1, 180.0)


def test_resolve_home_clamps_the_zone_radius_and_rejects_null_island() -> None:
    wide = resolve_home(
        {},
        fallback_latitude=52.1,
        fallback_longitude=5.1,
        fallback_radius=50_000,
    )
    tight = resolve_home(
        {},
        fallback_latitude=52.1,
        fallback_longitude=5.1,
        fallback_radius=1,
    )
    missing = resolve_home(
        {},
        fallback_latitude=0.0,
        fallback_longitude=0.0,
        fallback_radius=100,
    )
    assert wide is not None and wide.radius == 20000
    assert tight is not None and tight.radius == 10
    assert missing is None


def test_resolve_home_ignores_an_invalid_saved_circle() -> None:
    target = resolve_home(
        {CONF_HOME: {"latitude": 0, "longitude": 0, "radius": 100}},
        fallback_latitude=52.2,
        fallback_longitude=5.2,
        fallback_radius=None,
    )
    assert target is not None
    assert target.latitude == 52.2
    assert target.radius == 100


def test_suggested_home_uses_the_zone_when_present() -> None:
    assert suggested_home(latitude=52.3, longitude=4.8, radius=300) == {
        "latitude": 52.3,
        "longitude": 4.8,
        "radius": 300.0,
    }
    assert suggested_home(latitude=0.0, longitude=0.0, radius=100)["radius"] == 100.0
