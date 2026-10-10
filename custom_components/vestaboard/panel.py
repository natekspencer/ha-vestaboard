"""Sidebar panel for composing Vestaboard messages."""

from __future__ import annotations

import hashlib
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

PANEL_URL_PATH = "vestaboard"
PANEL_ELEMENT = "vestaboard-composer-panel"
STATIC_URL = "/vestaboard_static"

_DIRECTORY = Path(__file__).parent
_MODULE = _DIRECTORY / "frontend" / "vestaboard-composer.js"
_FONT = _DIRECTORY / "Vestaboard.otf"

DATA_PANEL = "panel_module_url"


async def async_setup_static_paths(hass: HomeAssistant) -> None:
    """Serve the panel's script and the Vestaboard font."""
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(f"{STATIC_URL}/{_MODULE.name}", str(_MODULE), True),
            StaticPathConfig(f"{STATIC_URL}/{_FONT.name}", str(_FONT), True),
        ]
    )
    # Version the script by its content so browsers don't keep a stale copy
    content = await hass.async_add_executor_job(_MODULE.read_bytes)
    version = hashlib.sha256(content).hexdigest()[:12]
    hass.data[DOMAIN][DATA_PANEL] = f"{STATIC_URL}/{_MODULE.name}?v={version}"


async def async_register_panel(hass: HomeAssistant) -> None:
    """Add the composer to the sidebar, if it isn't there already."""
    if PANEL_URL_PATH in hass.data.get(frontend.DATA_PANELS, {}):
        return
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_ELEMENT,
        sidebar_title="Vestaboard",
        sidebar_icon="mdi:dots-grid",
        module_url=hass.data[DOMAIN][DATA_PANEL],
        config={"font_url": f"{STATIC_URL}/{_FONT.name}"},
    )


@callback
def async_remove_panel_if_unused(hass: HomeAssistant, unloading_entry_id: str) -> None:
    """Remove the composer from the sidebar once no Vestaboard is loaded."""
    if any(
        entry.state is ConfigEntryState.LOADED and entry.entry_id != unloading_entry_id
        for entry in hass.config_entries.async_entries(DOMAIN)
    ):
        return
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
