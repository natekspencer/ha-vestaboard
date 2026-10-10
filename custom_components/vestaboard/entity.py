"""Vestaboard entity."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, format_mac
from homeassistant.helpers.entity import DeviceInfo, EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ENTRY_TYPE_DEVICE, ENTRY_TYPE_VIRTUAL
from .coordinator import (
    VestaboardArrayCoordinator,
    VestaboardConfigEntry,
    VestaboardCoordinator,
)
from .helpers import get_entry_type


class VestaboardEntity(
    CoordinatorEntity[VestaboardCoordinator | VestaboardArrayCoordinator]
):
    """Base class for Vestaboard entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: VestaboardConfigEntry,
        description: EntityDescription,
    ) -> None:
        """Construct a Vestaboard entity."""
        coordinator = entry.runtime_data
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}-{description.key}"

        entry_type = get_entry_type(entry)
        model = coordinator.model.name if coordinator.model else "Vestaboard"
        if entry_type == ENTRY_TYPE_VIRTUAL:
            model = f"Virtual {model}"
        device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Vestaboard",
            model=model,
            sw_version=coordinator.firmware_version,
        )
        if entry.unique_id and entry_type == ENTRY_TYPE_DEVICE:
            mac = format_mac(entry.unique_id)
            device_info["connections"] = {(CONNECTION_NETWORK_MAC, mac)}
        self._attr_device_info = device_info
