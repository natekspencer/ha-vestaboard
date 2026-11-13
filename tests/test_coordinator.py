"""Tests for the Vestaboard coordinator."""

from __future__ import annotations

from collections.abc import Generator
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import ClientConnectorError, ServerDisconnectedError
import pytest

from custom_components.vestaboard.const import DOMAIN, SERVICE_MESSAGE
from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
import homeassistant.util.dt as dt_util

from . import MockConfigEntry


def _refused() -> ClientConnectorError:
    """Return the error aiohttp raises when the board refuses a connection."""
    return ClientConnectorError(
        MagicMock(host="10.10.20.50", port=7000, ssl=None),
        ConnectionRefusedError(111, "Connect call failed"),
    )


@pytest.fixture(autouse=True)
def no_retry_delay() -> Generator[None]:
    """Retry writes without waiting."""
    with patch(
        "custom_components.vestaboard.coordinator.WRITE_RETRY_DELAYS", (0, 0, 0)
    ):
        yield


async def _send(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Send a message to the board through the message service."""
    (device,) = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_MESSAGE,
        {CONF_DEVICE_ID: [device.id], "message": "HELLO"},
        blocking=True,
    )


async def test_write_retried_after_refused_connection(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test a write goes through once the board takes connections again."""
    coordinator = init_integration.runtime_data
    with patch.object(
        coordinator.vestaboard,
        "write_message",
        AsyncMock(side_effect=[_refused(), _refused(), True]),
    ) as mock_write:
        await _send(hass, init_integration)

    assert mock_write.await_count == 3
    assert "HELLO" in coordinator.message


async def test_write_gives_up_after_retries(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test a board that keeps refusing raises a clear error."""
    coordinator = init_integration.runtime_data
    with (
        patch.object(
            coordinator.vestaboard,
            "write_message",
            AsyncMock(side_effect=_refused()),
        ) as mock_write,
        pytest.raises(HomeAssistantError, match="Couldn't connect to Vestaboard"),
    ):
        await _send(hass, init_integration)

    assert mock_write.await_count == 4


async def test_write_not_retried_once_sent(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test errors after connecting aren't retried, since the board may have the message."""
    coordinator = init_integration.runtime_data
    with (
        patch.object(
            coordinator.vestaboard,
            "write_message",
            AsyncMock(side_effect=ServerDisconnectedError()),
        ) as mock_write,
        pytest.raises(HomeAssistantError, match="Couldn't write message"),
    ):
        await _send(hass, init_integration)

    assert mock_write.await_count == 1


async def test_write_timeout_raises_clear_error(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test a write that times out raises a clear error."""
    coordinator = init_integration.runtime_data
    with (
        patch.object(
            coordinator.vestaboard,
            "write_message",
            AsyncMock(side_effect=TimeoutError()),
        ),
        pytest.raises(HomeAssistantError, match="Couldn't write message"),
    ):
        await _send(hass, init_integration)


async def test_refresh_during_revert_keeps_persistent_message(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test a refresh while a revert is retrying doesn't save the temporary message."""
    coordinator = init_integration.runtime_data
    board = coordinator.vestaboard
    rows, columns = len(board.data), len(board.data[0])
    persistent = [[1] * columns for _ in range(rows)]
    temporary = [[2] * columns for _ in range(rows)]

    await coordinator.async_write_message({"characters": persistent})
    await coordinator.async_write_message(
        {"characters": temporary}, dt_util.now() + timedelta(minutes=5)
    )

    write = board.write_message
    refreshed = False

    async def refuse_once_after_refresh(json, **kwargs):
        nonlocal refreshed
        if not refreshed:
            # The board still shows the temporary message while the revert retries
            refreshed = True
            await coordinator.async_refresh()
            raise _refused()
        return await write(json, **kwargs)

    with patch.object(board, "write_message", side_effect=refuse_once_after_refresh):
        await coordinator.async_clear_temporary_message()

    assert refreshed
    assert coordinator.persistent_message == persistent
    assert board.data == persistent
