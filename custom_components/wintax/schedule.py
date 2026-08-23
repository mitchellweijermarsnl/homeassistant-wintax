"""Weekday time windows that control when WinTax is polled.

The integration should only hit the portal during school pickup/drop-off,
and stay quiet the rest of the week.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta


@dataclass(frozen=True)
class PollWindow:
    """A daily clock window, inclusive on both start and end minutes."""

    start: time
    end: time


def parse_clock(value: str) -> time:
    """Parse `HH:MM` or `HH:MM:SS` into a time."""
    parts = value.strip().split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    return time(hour, minute)


def in_poll_window(
    now: datetime,
    windows: tuple[PollWindow, ...],
    *,
    weekdays_only: bool,
) -> bool:
    """Return True when *now* falls inside an allowed poll window."""
    if weekdays_only and now.weekday() >= 5:
        return False
    clock = (now.hour, now.minute)
    for window in windows:
        if _clock_tuple(window.start) <= clock <= _clock_tuple(window.end):
            return True
    return False


def seconds_until_next_poll(
    now: datetime,
    windows: tuple[PollWindow, ...],
    *,
    weekdays_only: bool,
    interval: timedelta,
) -> float:
    """Seconds until the coordinator should run again.

    Inside a window this is the configured interval. Outside a window it is
    the wait until the next weekday window starts.
    """
    if in_poll_window(now, windows, weekdays_only=weekdays_only):
        return max(interval.total_seconds(), 1)
    nxt = next_window_start(now, windows, weekdays_only=weekdays_only)
    return max((nxt - now).total_seconds(), 1)


def next_window_start(
    now: datetime,
    windows: tuple[PollWindow, ...],
    *,
    weekdays_only: bool,
) -> datetime:
    """Return the next datetime at which a poll window opens."""
    ordered = tuple(sorted(windows, key=lambda window: _clock_tuple(window.start)))
    if not ordered:
        return now + timedelta(hours=12)

    for day_offset in range(0, 8):
        day = now + timedelta(days=day_offset)
        if weekdays_only and day.weekday() >= 5:
            continue
        for window in ordered:
            candidate = day.replace(
                hour=window.start.hour,
                minute=window.start.minute,
                second=0,
                microsecond=0,
            )
            if candidate > now:
                return candidate
    return now + timedelta(days=1)


def _clock_tuple(value: time) -> tuple[int, int]:
    return (value.hour, value.minute)
