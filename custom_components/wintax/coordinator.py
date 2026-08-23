"""DataUpdateCoordinator for WinTax."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from zoneinfo import ZoneInfo
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import WinTaxAuthError, WinTaxClient, WinTaxError
from .const import (
    CONF_AFTERNOON_END,
    CONF_AFTERNOON_START,
    CONF_MORNING_END,
    CONF_MORNING_START,
    CONF_POLL_INTERVAL,
    CONF_WEEKDAYS_ONLY,
    DEFAULT_AFTERNOON_END,
    DEFAULT_AFTERNOON_START,
    DEFAULT_MORNING_END,
    DEFAULT_MORNING_START,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_TIMEZONE,
    DEFAULT_WEEKDAYS_ONLY,
    DOMAIN,
    RIDE_LOOKAHEAD_DAYS,
    RIDE_LOOKBACK_DAYS,
)
from .parser import Ride, TrackingData, parse_rides, parse_tracking, select_relevant_ride
from .schedule import (
    PollWindow,
    in_poll_window,
    parse_clock,
    seconds_until_next_poll,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WinTaxCoordinatorData:
    """Snapshot consumed by all WinTax entities."""

    rides: tuple[Ride, ...]
    relevant_ride: Ride | None
    tracking: TrackingData | None
    fetched_at: datetime
    polling_active: bool


class WinTaxCoordinator(DataUpdateCoordinator[WinTaxCoordinatorData]):
    """Fetch rides during configured weekday windows only."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: WinTaxClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=config_entry,
            update_interval=timedelta(seconds=DEFAULT_POLL_INTERVAL_SECONDS),
        )
        self.client = client

    def _timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.hass.config.time_zone)
        except Exception:  # noqa: BLE001 - fall back to the portal's timezone
            return DEFAULT_TIMEZONE

    def _poll_windows(self) -> tuple[PollWindow, ...]:
        options = self.config_entry.options
        return (
            PollWindow(
                parse_clock(options.get(CONF_MORNING_START, DEFAULT_MORNING_START)),
                parse_clock(options.get(CONF_MORNING_END, DEFAULT_MORNING_END)),
            ),
            PollWindow(
                parse_clock(options.get(CONF_AFTERNOON_START, DEFAULT_AFTERNOON_START)),
                parse_clock(options.get(CONF_AFTERNOON_END, DEFAULT_AFTERNOON_END)),
            ),
        )

    def _weekdays_only(self) -> bool:
        return bool(
            self.config_entry.options.get(CONF_WEEKDAYS_ONLY, DEFAULT_WEEKDAYS_ONLY)
        )

    def _poll_interval(self) -> timedelta:
        seconds = int(
            self.config_entry.options.get(
                CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_SECONDS
            )
        )
        return timedelta(seconds=seconds)

    def _schedule_next_refresh(self, now: datetime) -> None:
        delay = seconds_until_next_poll(
            now,
            self._poll_windows(),
            weekdays_only=self._weekdays_only(),
            interval=self._poll_interval(),
        )
        self.update_interval = timedelta(seconds=delay)

    async def _async_update_data(self) -> WinTaxCoordinatorData:
        tz = self._timezone()
        now = dt_util.now(tz)
        windows = self._poll_windows()
        weekdays_only = self._weekdays_only()
        polling = in_poll_window(now, windows, weekdays_only=weekdays_only)
        self._schedule_next_refresh(now)

        if not polling:
            _LOGGER.debug("Outside WinTax poll window; sleeping until next window")
            if self.data is not None:
                return WinTaxCoordinatorData(
                    rides=self.data.rides,
                    relevant_ride=self.data.relevant_ride,
                    tracking=self.data.tracking,
                    fetched_at=self.data.fetched_at,
                    polling_active=False,
                )
            return WinTaxCoordinatorData(
                rides=(),
                relevant_ride=None,
                tracking=None,
                fetched_at=now,
                polling_active=False,
            )

        start = (now - timedelta(days=RIDE_LOOKBACK_DAYS)).date()
        end = (now + timedelta(days=RIDE_LOOKAHEAD_DAYS)).date()

        try:
            html = await self.client.async_fetch_rides(start, end)
        except WinTaxAuthError as err:
            raise ConfigEntryAuthFailed("WinTax authentication failed") from err
        except WinTaxError as err:
            raise UpdateFailed(str(err)) from err

        rides = await self.hass.async_add_executor_job(
            partial(parse_rides, html, tz=tz)
        )
        relevant = select_relevant_ride(rides, now)

        tracking: TrackingData | None = None
        if relevant is not None and relevant.tracking_available and relevant.trip_id:
            try:
                map_html = await self.client.async_fetch_tracking(relevant.trip_id)
            except WinTaxAuthError as err:
                raise ConfigEntryAuthFailed("WinTax authentication failed") from err
            except WinTaxError as err:
                _LOGGER.debug("WinTax tracking fetch failed: %s", err)
            else:
                tracking = await self.hass.async_add_executor_job(
                    partial(parse_tracking, map_html, trip_id=relevant.trip_id)
                )

        return WinTaxCoordinatorData(
            rides=tuple(rides),
            relevant_ride=relevant,
            tracking=tracking,
            fetched_at=now,
            polling_active=True,
        )
