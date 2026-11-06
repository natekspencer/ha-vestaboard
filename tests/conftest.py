"""Fixtures for Vestaboard tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant

from . import MockConfigEntry, setup_virtual_board


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in all tests."""


@pytest.fixture(autouse=True)
def mock_panel(hass: HomeAssistant) -> Generator[AsyncMock]:
    """Stub the dependencies used to serve the composer panel.

    The real frontend needs the large home-assistant-frontend package.
    """
    hass.config.components.update({"frontend", "http", "panel_custom", "websocket_api"})
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    with patch(
        "custom_components.vestaboard.panel.panel_custom.async_register_panel"
    ) as async_register_panel:
        yield async_register_panel


@pytest.fixture
async def init_integration(hass: HomeAssistant) -> MockConfigEntry:
    """Set up the Vestaboard integration with a virtual board."""
    return await setup_virtual_board(hass)
