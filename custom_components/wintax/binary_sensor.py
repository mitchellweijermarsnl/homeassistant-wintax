"""WinTax binary sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import WinTaxCoordinator
from .entity import WinTaxEntity

PARALLEL_UPDATES = 0

SENSOR_TRACKING_AVAILABLE = "tracking_available"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WinTax binary sensors from a config entry."""
    coordinator: WinTaxCoordinator = entry.runtime_data
    async_add_entities([WinTaxTrackingAvailableSensor(coordinator)])


class WinTaxTrackingAvailableSensor(WinTaxEntity, BinarySensorEntity):
    """On when the selected ride has a tracking link and usable GPS data."""

    def __init__(self, coordinator: WinTaxCoordinator) -> None:
        super().__init__(coordinator, SENSOR_TRACKING_AVAILABLE)
        self._attr_name = "Tracking available"
        self._attr_translation_key = SENSOR_TRACKING_AVAILABLE
        self._attr_icon = "mdi:map-marker-radius"

    @property
    def is_on(self) -> bool:
        """Return True when tracking exists and coordinates were parsed."""
        ride = self.ride
        tracking = (
            self.coordinator.data.tracking if self.coordinator.data else None
        )
        if ride is None or not ride.tracking_available:
            return False
        return bool(tracking is not None and tracking.has_coordinates)
