"""Tests for the Vestaboard websocket commands."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.vestaboard.websocket import websocket_boards
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from . import MockConfigEntry


async def test_boards(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test a loaded board is listed with its device, using no deprecated calls."""
    (device,) = dr.async_entries_for_config_entry(
        dr.async_get(hass), init_integration.entry_id
    )
    connection = MagicMock()

    websocket_boards(hass, connection, {"id": 1, "type": "vestaboard/boards"})
    await hass.async_block_till_done(wait_background_tasks=True)

    connection.send_result.assert_called_once()
    message_id, result = connection.send_result.call_args.args
    assert message_id == 1
    (board,) = result["boards"]
    assert board["device_id"] == device.id
    assert board["name"] == "Test board"
    assert "which is deprecated" not in caplog.text
