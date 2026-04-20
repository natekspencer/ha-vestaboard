"""Vestaboard sensor entity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import VestaboardConfigEntry, VestaboardCoordinator
from .entity import VestaboardEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VestaboardConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vestaboard sensors using config entry."""
    async_add_entities(
        VestaboardSensorEntity(entry, description) for description in SENSORS
    )


@dataclass(kw_only=True)
class VestaboardSensorEntityDescription(SensorEntityDescription):
    value_fn: Callable[[VestaboardCoordinator], datetime | str | None]


SENSORS = (
    VestaboardSensorEntityDescription(
        key="message",
        translation_key="message",
        value_fn=lambda coor: coor.message,
    ),
    VestaboardSensorEntityDescription(
        key="temporary_message_expiration",
        translation_key="temporary_message_expiration",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coor: coor.temporary_message_expiration,
    ),
)


class VestaboardSensorEntity(VestaboardEntity, SensorEntity):
    """Vestaboard sensor entity."""

    entity_description: VestaboardSensorEntityDescription

    @property
    def native_value(self) -> str | None:
        """Return the value reported by the sensor."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return entity specific state attributes."""
        if self.entity_description.key == "message" and (data := self.coordinator.data):
            character_codes = "".join(f"{{{code}}}" for row in data for code in row)
            attrs: dict[str, Any] = {"character_codes": character_codes}
            if (board_model := self.coordinator.model) is not None:
                attrs["model"] = board_model.model
                attrs["color"] = board_model.color
            return attrs
        return None
