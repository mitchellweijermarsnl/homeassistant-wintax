"""The WinTax Home Assistant custom integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

PLATFORMS = ["binary_sensor", "device_tracker", "sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up WinTax from a config entry."""
    from datetime import timedelta

    from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from .api import WinTaxClient
    from .const import DEFAULT_BASE_URL, DEFAULT_SCAN_INTERVAL
    from .coordinator import WinTaxCoordinator

    session = async_get_clientsession(hass)
    client = WinTaxClient(
        session,
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        base_url=DEFAULT_BASE_URL,
    )

    scan_seconds = entry.options.get(
        CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds())
    )
    coordinator = WinTaxCoordinator(
        hass,
        entry,
        client,
        update_interval=timedelta(seconds=scan_seconds),
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a WinTax config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


# Imported by Home Assistant when loading the integration.
__all__ = ["DOMAIN", "PLATFORMS", "async_setup_entry", "async_unload_entry"]
