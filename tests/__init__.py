"""Tests for the Vestaboard integration."""

from __future__ import annotations

from custom_components.vestaboard.const import (
    CONF_BOARD_MODEL,
    CONF_ENTRY_TYPE,
    DOMAIN,
    ENTRY_TYPE_VIRTUAL,
)
from custom_components.vestaboard.vestaboard_model import MODEL_FLAGSHIP
from homeassistant.core import HomeAssistant

try:
    from pytest_homeassistant.common import MockConfigEntry
except ImportError:  # Home Assistant < 2026.11
    from pytest_homeassistant_custom_component.common import MockConfigEntry


async def setup_virtual_board(
    hass: HomeAssistant, title: str = "Test board", model: str = MODEL_FLAGSHIP
) -> MockConfigEntry:
    """Set up a virtual Vestaboard, which needs no hardware or network."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=title,
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_VIRTUAL, CONF_BOARD_MODEL: model},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    return entry
