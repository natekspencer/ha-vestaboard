"""Vestaboard time entity."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import time

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_QUIET_END, CONF_QUIET_START
from .coordinator import (
    VestaboardArrayCoordinator,
    VestaboardConfigEntry,
    VestaboardCoordinator,
)
from .entity import VestaboardEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VestaboardConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vestaboard times using config entry."""
    async_add_entities(
        VestaboardTimeEntity(entry, description) for description in TIMES
    )


@dataclass(frozen=True, kw_only=True)
class VestaboardTimeEntityDescription(TimeEntityDescription):
    """Vestaboard time entity description."""

    value_fn: Callable[
        [VestaboardCoordinator | VestaboardArrayCoordinator], time | None
    ]


TIMES = (
    VestaboardTimeEntityDescription(
        key=CONF_QUIET_START,
        translation_key=CONF_QUIET_START,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda coor: coor.quiet_start,
    ),
    VestaboardTimeEntityDescription(
        key=CONF_QUIET_END,
        translation_key=CONF_QUIET_END,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda coor: coor.quiet_end,
    ),
)


class VestaboardTimeEntity(VestaboardEntity, TimeEntity):
    """Vestaboard time entity, stored in the config entry's options."""

    entity_description: VestaboardTimeEntityDescription

    @property
    def native_value(self) -> time | None:
        """Return the time."""
        return self.entity_description.value_fn(self.coordinator)

    async def async_set_value(self, value: time) -> None:
        """Change the time."""
        self._async_update_options(
            {self.entity_description.key: value.strftime("%H:%M:%S")}
        )
