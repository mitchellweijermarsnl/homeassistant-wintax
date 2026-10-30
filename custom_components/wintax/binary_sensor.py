"""WinTax binary sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import WinTaxCoordinator
from .entity import WinTaxEntity

PARALLEL_UPDATES = 0

SENSOR_TRACKING_AVAILABLE = "tracking_available"
SENSOR_NEAR_HOME = "near_home"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WinTax binary sensors from a config entry."""
    coordinator: WinTaxCoordinator = entry.runtime_data
    async_add_entities(
        [
            WinTaxTrackingAvailableSensor(coordinator),
            WinTaxNearHomeSensor(coordinator),
        ]
    )


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


class WinTaxNearHomeSensor(WinTaxEntity, BinarySensorEntity):
    """On when the vehicle GPS position is inside the configured home circle."""

    _attr_device_class = BinarySensorDeviceClass.PRESENCE

    def __init__(self, coordinator: WinTaxCoordinator) -> None:
        super().__init__(coordinator, SENSOR_NEAR_HOME)
        self._attr_name = "Near home"
        self._attr_translation_key = SENSOR_NEAR_HOME
        self._attr_icon = "mdi:home-map-marker"

    @property
    def available(self) -> bool:
        """Stay unavailable without a GPS fix, so automations do not see 'off'."""
        return super().available and self.coordinator.distance_to_home() is not None

    @property
    def is_on(self) -> bool:
        """Return True when the vehicle is inside or on the home circle."""
        distance = self.coordinator.distance_to_home()
        home = self.coordinator.home_target()
        if distance is None or home is None:
            return False
        return distance <= home.radius

    @property
    def extra_state_attributes(self) -> dict[str, float | bool]:
        """Expose the circle size and whether the last poll is still running."""
        attrs: dict[str, float | bool] = {}
        home = self.coordinator.home_target()
        if home is not None:
            attrs["radius"] = home.radius
        if self.coordinator.data is not None:
            attrs["polling_active"] = self.coordinator.data.polling_active
        return attrs
