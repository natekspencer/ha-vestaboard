"""Vestaboard sensor entity."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import MAX_LENGTH_STATE_STATE
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


def _state_message(message: str | None) -> str | None:
    """Fit a message within the state length limit.

    Only arrays have messages long enough to need this. Blank space is trimmed
    first and anything still too long is truncated; the full message is
    available as an attribute.
    """
    if message is None or len(message) <= MAX_LENGTH_STATE_STATE:
        return message
    message = "\n".join(line.rstrip() for line in message.splitlines()).strip("\n")
    if len(message) <= MAX_LENGTH_STATE_STATE:
        return message
    return message[: MAX_LENGTH_STATE_STATE - 1] + "…"


@dataclass(kw_only=True)
class VestaboardSensorEntityDescription(SensorEntityDescription):
    value_fn: Callable[[VestaboardCoordinator], datetime | str | None]


SENSORS = (
    VestaboardSensorEntityDescription(
        key="message",
        translation_key="message",
        value_fn=lambda coor: _state_message(coor.message),
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
            attributes = {"character_codes": character_codes}
            if (message := self.coordinator.message) and len(
                message
            ) > MAX_LENGTH_STATE_STATE:
                attributes["full_message"] = message
            return attributes
        return None
