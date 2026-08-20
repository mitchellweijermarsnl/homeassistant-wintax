"""Shared entity helpers for WinTax."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DEFAULT_BASE_URL, DOMAIN, MANUFACTURER, MODEL
from .coordinator import WinTaxCoordinator
from .parser import Ride


class WinTaxEntity(CoordinatorEntity[WinTaxCoordinator]):
    """Base class for WinTax coordinator entities."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(self, coordinator: WinTaxCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name="WinTax",
            manufacturer=MANUFACTURER,
            model=MODEL,
            configuration_url=f"{DEFAULT_BASE_URL}/client/",
        )

    @property
    def ride(self) -> Ride | None:
        """Return the currently selected ride, if any."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.relevant_ride
