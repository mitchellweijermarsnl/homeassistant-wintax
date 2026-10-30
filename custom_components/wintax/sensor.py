"""WinTax sensors."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfLength
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import WinTaxCoordinator
from .entity import WinTaxEntity
from .parser import Ride

PARALLEL_UPDATES = 0

SENSOR_NEXT_RIDE = "next_ride"
SENSOR_NEXT_RIDE_START = "next_ride_start"
SENSOR_NEXT_RIDE_END = "next_ride_end"
SENSOR_RIDE_STATUS = "ride_status"
SENSOR_DISTANCE_HOME = "distance_home"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WinTax sensors from a config entry."""
    coordinator: WinTaxCoordinator = entry.runtime_data
    async_add_entities(
        [
            WinTaxNextRideSensor(coordinator),
            WinTaxTimestampSensor(
                coordinator,
                key=SENSOR_NEXT_RIDE_START,
                name="Next ride start",
                start=True,
            ),
            WinTaxTimestampSensor(
                coordinator,
                key=SENSOR_NEXT_RIDE_END,
                name="Next ride end",
                start=False,
            ),
            WinTaxRideStatusSensor(coordinator),
            WinTaxDistanceHomeSensor(coordinator),
        ]
    )


class WinTaxNextRideSensor(WinTaxEntity, SensorEntity):
    """Human-readable status of the current or next ride."""

    def __init__(self, coordinator: WinTaxCoordinator) -> None:
        super().__init__(coordinator, SENSOR_NEXT_RIDE)
        self._attr_name = "Next ride"
        self._attr_translation_key = SENSOR_NEXT_RIDE
        self._attr_icon = "mdi:bus-clock"

    @property
    def native_value(self) -> StateType:
        """Return a useful status string."""
        ride = self.ride
        if ride is None:
            return "Geen ritten"
        if ride.status:
            return ride.status
        # WinTax omits a status chip for ordinary scheduled rides.
        return "Gepland"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return structured ride details without passenger names."""
        attrs: dict[str, Any] = {}
        if self.coordinator.data is not None:
            attrs["polling_active"] = self.coordinator.data.polling_active
        ride = self.ride
        if ride is not None:
            attrs.update(_ride_attributes(ride))
        return attrs


class WinTaxTimestampSensor(WinTaxEntity, SensorEntity):
    """Timestamp for the selected ride's planned start or end."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: WinTaxCoordinator,
        *,
        key: str,
        name: str,
        start: bool,
    ) -> None:
        super().__init__(coordinator, key)
        self._start = start
        self._attr_name = name
        self._attr_translation_key = key
        self._attr_icon = "mdi:clock-start" if start else "mdi:clock-end"

    @property
    def native_value(self) -> datetime | None:
        """Return the planned start or end of the selected ride."""
        ride = self.ride
        if ride is None:
            return None
        if self._start:
            return ride.actual_start or ride.planned_start
        return ride.actual_end or ride.planned_end


class WinTaxRideStatusSensor(WinTaxEntity, SensorEntity):
    """Exact status label from WinTax, when one is present."""

    def __init__(self, coordinator: WinTaxCoordinator) -> None:
        super().__init__(coordinator, SENSOR_RIDE_STATUS)
        self._attr_name = "Ride status"
        self._attr_translation_key = SENSOR_RIDE_STATUS
        self._attr_icon = "mdi:list-status"

    @property
    def native_value(self) -> StateType:
        """Return the status chip text from WinTax, or None."""
        ride = self.ride
        if ride is None:
            return None
        return ride.status


class WinTaxDistanceHomeSensor(WinTaxEntity, SensorEntity):
    """Distance from the vehicle to the configured home pin, in meters."""

    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfLength.METERS
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: WinTaxCoordinator) -> None:
        super().__init__(coordinator, SENSOR_DISTANCE_HOME)
        self._attr_name = "Distance to home"
        self._attr_translation_key = SENSOR_DISTANCE_HOME
        self._attr_icon = "mdi:map-marker-distance"

    @property
    def available(self) -> bool:
        """Stay unavailable without a GPS fix, so a missing position is not 0 m."""
        return super().available and self.coordinator.distance_to_home() is not None

    @property
    def native_value(self) -> float | None:
        """Return the distance in meters, or None when GPS or home is unknown."""
        return self.coordinator.distance_to_home()

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


def _ride_attributes(ride: Ride) -> dict[str, Any]:
    return {
        "trip_id": ride.trip_id,
        "date": ride.ride_date.isoformat() if ride.ride_date else None,
        "planned_start": _iso(ride.planned_start),
        "planned_end": _iso(ride.planned_end),
        "actual_start": _iso(ride.actual_start),
        "actual_end": _iso(ride.actual_end),
        "origin": ride.origin,
        "destination": ride.destination,
        "passengers": ride.passenger_count,
        "status": ride.status,
        "tracking_available": ride.tracking_available,
        "is_return": ride.is_return,
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
