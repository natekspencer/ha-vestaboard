"""Tests for the Vestaboard integration setup."""

from __future__ import annotations

from unittest.mock import AsyncMock

from custom_components.vestaboard.const import DOMAIN, SERVICE_MESSAGE
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from . import MockConfigEntry

PLATFORM_DOMAINS = {"binary_sensor", "button", "image", "sensor", "switch", "time"}


def _device(hass: HomeAssistant, entry: MockConfigEntry) -> dr.DeviceEntry:
    """Return the only device of a config entry."""
    (device,) = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    return device


async def test_setup_and_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_panel: AsyncMock
) -> None:
    """Test a board loads its entities and panel, and unloads cleanly."""
    entry = init_integration
    assert entry.state is ConfigEntryState.LOADED
    mock_panel.assert_awaited_once()

    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert {entity.domain for entity in entities} == PLATFORM_DOMAINS

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_device_registered(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test a virtual board is registered as a device."""
    device = _device(hass, init_integration)

    assert device.name == "Test board"
    assert device.manufacturer == "Vestaboard"
    assert device.model.startswith("Virtual ")


async def test_send_message(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test the message service writes to the board."""
    device = _device(hass, init_integration)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_MESSAGE,
        {CONF_DEVICE_ID: [device.id], "message": "HELLO"},
        blocking=True,
    )
    await hass.async_block_till_done()

    coordinator = init_integration.runtime_data
    assert any(any(row) for row in coordinator.vestaboard.data)
    assert "HELLO" in coordinator.message
