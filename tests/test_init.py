"""Tests for the Vestaboard integration setup."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from custom_components.vestaboard.const import DOMAIN, SERVICE_MESSAGE
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_DEVICE_ID, STATE_UNAVAILABLE
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
    for entity in entities:
        if not entity.disabled:
            assert hass.states.get(entity.entity_id).state != STATE_UNAVAILABLE

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_panel_registered(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_panel: AsyncMock
) -> None:
    """Test the composer panel loads the files served by the integration."""
    hass.http.async_register_static_paths.assert_awaited_once()
    script, font = hass.http.async_register_static_paths.await_args.args[0]
    assert script.url_path == "/vestaboard_static/vestaboard-composer.js"
    assert font.url_path == "/vestaboard_static/Vestaboard.otf"
    assert Path(script.path).is_file()
    assert Path(font.path).is_file()

    panel = mock_panel.await_args.kwargs
    assert panel["frontend_url_path"] == "vestaboard"
    assert panel["module_url"].startswith(f"{script.url_path}?v=")
    assert panel["config"] == {"font_url": font.url_path}


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
