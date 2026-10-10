"""Vestaboard switch entity."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_QUIET_END, CONF_QUIET_HOURS, CONF_QUIET_START
from .coordinator import VestaboardConfigEntry
from .entity import VestaboardEntity

# Quiet hours used when turning them on before any times are set
DEFAULT_QUIET_START = "22:00:00"
DEFAULT_QUIET_END = "07:00:00"

QUIET_HOURS = SwitchEntityDescription(
    key=CONF_QUIET_HOURS,
    translation_key=CONF_QUIET_HOURS,
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VestaboardConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vestaboard switches using config entry."""
    async_add_entities([VestaboardQuietHoursSwitch(entry, QUIET_HOURS)])


class VestaboardQuietHoursSwitch(VestaboardEntity, SwitchEntity):
    """Turns quiet hours on or off, stored in the config entry's options."""

    @property
    def is_on(self) -> bool:
        """Return true if quiet hours are on."""
        return self.coordinator.quiet_hours_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn quiet hours on, with default times if none are set."""
        changes: dict[str, Any] = {CONF_QUIET_HOURS: True}
        options = self.coordinator.config_entry.options
        if not options.get(CONF_QUIET_START):
            changes[CONF_QUIET_START] = DEFAULT_QUIET_START
        if not options.get(CONF_QUIET_END):
            changes[CONF_QUIET_END] = DEFAULT_QUIET_END
        self._async_update_options(changes)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn quiet hours off."""
        self._async_update_options({CONF_QUIET_HOURS: False})
