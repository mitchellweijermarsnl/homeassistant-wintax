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
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEZONE,
    DOMAIN,
    RIDE_LOOKAHEAD_DAYS,
    RIDE_LOOKBACK_DAYS,
)
from .parser import Ride, TrackingData, parse_rides, parse_tracking, select_relevant_ride

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WinTaxCoordinatorData:
    """Snapshot consumed by all WinTax entities."""

    rides: tuple[Ride, ...]
    relevant_ride: Ride | None
    tracking: TrackingData | None
    fetched_at: datetime


class WinTaxCoordinator(DataUpdateCoordinator[WinTaxCoordinatorData]):
    """Fetch rides once per interval and share the result with all entities."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: WinTaxClient,
        update_interval: timedelta = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=config_entry,
            update_interval=update_interval,
        )
        self.client = client

    def _timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.hass.config.time_zone)
        except Exception:  # noqa: BLE001 - fall back to the portal's timezone
            return DEFAULT_TIMEZONE

    async def _async_update_data(self) -> WinTaxCoordinatorData:
        tz = self._timezone()
        now = dt_util.now(tz)
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
        )
