"""Tests for weekday poll windows."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from custom_components.wintax.schedule import (
    PollWindow,
    in_poll_window,
    next_window_start,
    parse_clock,
    seconds_until_next_poll,
)

TZ = ZoneInfo("Europe/Amsterdam")
WINDOWS = (
    PollWindow(parse_clock("06:30"), parse_clock("08:30")),
    PollWindow(parse_clock("14:00"), parse_clock("15:30")),
)


def _at(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


def test_parse_clock_accepts_hhmm_and_seconds() -> None:
    assert parse_clock("06:30") == parse_clock("06:30:00")
    assert parse_clock("15:30:00").hour == 15
    assert parse_clock("15:30:00").minute == 30


def test_weekday_morning_and_afternoon_windows() -> None:
    # Monday 23 Aug 2026
    assert in_poll_window(_at(2026, 8, 24, 6, 29), WINDOWS, weekdays_only=True) is False
    assert in_poll_window(_at(2026, 8, 24, 6, 30), WINDOWS, weekdays_only=True) is True
    assert in_poll_window(_at(2026, 8, 24, 8, 30), WINDOWS, weekdays_only=True) is True
    assert in_poll_window(_at(2026, 8, 24, 8, 31), WINDOWS, weekdays_only=True) is False
    assert in_poll_window(_at(2026, 8, 24, 14, 0), WINDOWS, weekdays_only=True) is True
    assert in_poll_window(_at(2026, 8, 24, 15, 30), WINDOWS, weekdays_only=True) is True
    assert in_poll_window(_at(2026, 8, 24, 15, 31), WINDOWS, weekdays_only=True) is False


def test_weekend_is_never_polled() -> None:
    saturday = _at(2026, 8, 22, 7, 0)
    sunday = _at(2026, 8, 23, 14, 15)
    assert in_poll_window(saturday, WINDOWS, weekdays_only=True) is False
    assert in_poll_window(sunday, WINDOWS, weekdays_only=True) is False


def test_next_window_after_morning_is_afternoon() -> None:
    now = _at(2026, 8, 24, 8, 31)
    nxt = next_window_start(now, WINDOWS, weekdays_only=True)
    assert nxt == _at(2026, 8, 24, 14, 0)


def test_next_window_after_friday_afternoon_is_monday_morning() -> None:
    now = _at(2026, 8, 21, 15, 31)  # Friday
    nxt = next_window_start(now, WINDOWS, weekdays_only=True)
    assert nxt == _at(2026, 8, 24, 6, 30)  # Monday


def test_next_window_on_saturday_is_monday_morning() -> None:
    now = _at(2026, 8, 22, 10, 0)
    nxt = next_window_start(now, WINDOWS, weekdays_only=True)
    assert nxt == _at(2026, 8, 24, 6, 30)


def test_inside_window_delay_is_interval() -> None:
    now = _at(2026, 8, 24, 7, 0)
    delay = seconds_until_next_poll(
        now, WINDOWS, weekdays_only=True, interval=timedelta(seconds=10)
    )
    assert delay == 10


def test_outside_window_delay_reaches_next_start() -> None:
    now = _at(2026, 8, 24, 12, 0)
    delay = seconds_until_next_poll(
        now, WINDOWS, weekdays_only=True, interval=timedelta(seconds=10)
    )
    assert delay == 2 * 3600  # 14:00
