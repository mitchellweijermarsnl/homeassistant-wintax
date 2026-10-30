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
    CONF_ACTIVE_GRACE_MINUTES,
    CONF_AFTERNOON_END,
    CONF_AFTERNOON_START,
    CONF_MORNING_END,
    CONF_MORNING_START,
    CONF_POLL_INTERVAL,
    CONF_RIDE_LOOKAHEAD_DAYS,
    CONF_RIDE_LOOKBACK_DAYS,
    CONF_WEEKDAYS_ONLY,
    DEFAULT_ACTIVE_GRACE_MINUTES,
    DEFAULT_AFTERNOON_END,
    DEFAULT_AFTERNOON_START,
    DEFAULT_MORNING_END,
    DEFAULT_MORNING_START,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_TIMEZONE,
    DEFAULT_WEEKDAYS_ONLY,
    DOMAIN,
    MAX_ACTIVE_GRACE_MINUTES,
    MAX_POLL_INTERVAL_SECONDS,
    MAX_RIDE_LOOKAHEAD_DAYS,
    MAX_RIDE_LOOKBACK_DAYS,
    MIN_ACTIVE_GRACE_MINUTES,
    MIN_POLL_INTERVAL_SECONDS,
    MIN_RIDE_LOOKAHEAD_DAYS,
    MIN_RIDE_LOOKBACK_DAYS,
    RIDE_LOOKAHEAD_DAYS,
    RIDE_LOOKBACK_DAYS,
)
from .geo import HomeTarget, distance_meters, resolve_home
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
        seconds = self._option_int(
            CONF_POLL_INTERVAL,
            DEFAULT_POLL_INTERVAL_SECONDS,
            MIN_POLL_INTERVAL_SECONDS,
            MAX_POLL_INTERVAL_SECONDS,
        )
        return timedelta(seconds=seconds)

    def _ride_lookback_days(self) -> int:
        return self._option_int(
            CONF_RIDE_LOOKBACK_DAYS,
            RIDE_LOOKBACK_DAYS,
            MIN_RIDE_LOOKBACK_DAYS,
            MAX_RIDE_LOOKBACK_DAYS,
        )

    def _ride_lookahead_days(self) -> int:
        return self._option_int(
            CONF_RIDE_LOOKAHEAD_DAYS,
            RIDE_LOOKAHEAD_DAYS,
            MIN_RIDE_LOOKAHEAD_DAYS,
            MAX_RIDE_LOOKAHEAD_DAYS,
        )

    def _active_grace_minutes(self) -> int:
        return self._option_int(
            CONF_ACTIVE_GRACE_MINUTES,
            DEFAULT_ACTIVE_GRACE_MINUTES,
            MIN_ACTIVE_GRACE_MINUTES,
            MAX_ACTIVE_GRACE_MINUTES,
        )

    def _option_int(self, key: str, default: int, low: int, high: int) -> int:
        raw = self.config_entry.options.get(key, default)
        try:
            number = int(raw)
        except (TypeError, ValueError):
            return default
        return min(max(number, low), high)

    def home_target(self) -> HomeTarget | None:
        """Return the saved home circle, or the Home Assistant home zone."""
        latitude = self.hass.config.latitude
        longitude = self.hass.config.longitude
        radius: float | None = None
        zone = self.hass.states.get("zone.home")
        if zone is not None:
            latitude = zone.attributes.get("latitude", latitude)
            longitude = zone.attributes.get("longitude", longitude)
            raw_radius = zone.attributes.get("radius")
            if isinstance(raw_radius, (int, float)) and not isinstance(raw_radius, bool):
                radius = float(raw_radius)
        try:
            fallback_latitude = float(latitude)
            fallback_longitude = float(longitude)
        except (TypeError, ValueError):
            return resolve_home(
                self.config_entry.options,
                fallback_latitude=None,
                fallback_longitude=None,
                fallback_radius=None,
            )
        return resolve_home(
            self.config_entry.options,
            fallback_latitude=fallback_latitude,
            fallback_longitude=fallback_longitude,
            fallback_radius=radius,
        )

    def distance_to_home(self) -> float | None:
        """Return meters from the vehicle to the home circle, if both are known."""
        if self.data is None:
            return None
        tracking = self.data.tracking
        if tracking is None or not tracking.has_coordinates:
            return None
        home = self.home_target()
        if home is None or tracking.latitude is None or tracking.longitude is None:
            return None
        return distance_meters(
            home.latitude,
            home.longitude,
            tracking.latitude,
            tracking.longitude,
        )

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

        start = (now - timedelta(days=self._ride_lookback_days())).date()
        end = (now + timedelta(days=self._ride_lookahead_days())).date()

        try:
            html = await self.client.async_fetch_rides(start, end)
        except WinTaxAuthError as err:
            raise ConfigEntryAuthFailed("WinTax authentication failed") from err
        except WinTaxError as err:
            raise UpdateFailed(str(err)) from err

        rides = await self.hass.async_add_executor_job(
            partial(parse_rides, html, tz=tz)
        )
        relevant = select_relevant_ride(
            rides, now, grace_minutes=self._active_grace_minutes()
        )

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
