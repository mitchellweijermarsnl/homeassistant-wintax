"""WinTax device tracker.

Created only when map.wts yields valid GPS coordinates. No placeholder location
is published. The entity is added dynamically if coordinates appear later.
"""

from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import WinTaxCoordinator
from .entity import WinTaxEntity

PARALLEL_UPDATES = 0

ENTITY_KEY = "vehicle"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the vehicle tracker only when coordinates are available."""
    coordinator: WinTaxCoordinator = entry.runtime_data
    added = False

    @callback
    def _maybe_add() -> None:
        nonlocal added
        if added or coordinator.data is None:
            return
        tracking = coordinator.data.tracking
        if tracking is None or not tracking.has_coordinates:
            return
        async_add_entities([WinTaxVehicleTracker(coordinator)])
        added = True

    _maybe_add()
    entry.async_on_unload(coordinator.async_add_listener(_maybe_add))


class WinTaxVehicleTracker(WinTaxEntity, TrackerEntity):
    """GPS position of the vehicle, when WinTax actually provides one."""

    _attr_name = "Vehicle"
    _attr_source_type = SourceType.GPS
    _attr_translation_key = "vehicle"

    def __init__(self, coordinator: WinTaxCoordinator) -> None:
        super().__init__(coordinator, ENTITY_KEY)

    @property
    def latitude(self) -> float | None:
        """Return latitude from map.wts, or None."""
        tracking = self.coordinator.data.tracking if self.coordinator.data else None
        if tracking is None or not tracking.has_coordinates:
            return None
        return tracking.latitude

    @property
    def longitude(self) -> float | None:
        """Return longitude from map.wts, or None."""
        tracking = self.coordinator.data.tracking if self.coordinator.data else None
        if tracking is None or not tracking.has_coordinates:
            return None
        return tracking.longitude

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Expose the trip id used for the tracking request."""
        tracking = self.coordinator.data.tracking if self.coordinator.data else None
        ride = self.ride
        return {
            "trip_id": (tracking.trip_id if tracking else None) or (ride.trip_id if ride else None),
            "status": tracking.status if tracking else (ride.status if ride else None),
        }
