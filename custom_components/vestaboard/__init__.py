"""Support for Vestaboard."""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .client import VestaboardVirtualClient
from .const import (
    COLOR_BLACK,
    CONF_BOARD_MODEL,
    DATA_HASS_CONFIG,
    DOMAIN,
    ENTRY_TYPE_VIRTUAL,
)
from .coordinator import VestaboardConfigEntry, VestaboardCoordinator
from .helpers import create_client, get_entry_type
from .services import async_setup_services
from .vestaboard_model import VestaboardModel

_LOGGER = logging.getLogger(__name__)

VIRTUAL_STORAGE_VERSION = 1
# Seconds to wait before saving a virtual board's message, to batch rapid writes
VIRTUAL_SAVE_DELAY = 1

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.IMAGE,
    Platform.SENSOR,
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Vestaboard integration."""
    async_setup_services(hass)
    hass.data[DOMAIN] = {DATA_HASS_CONFIG: config}
    return True


async def async_setup_entry(hass: HomeAssistant, entry: VestaboardConfigEntry) -> bool:
    """Set up Vestaboard from a config entry."""
    store = None
    if get_entry_type(entry) == ENTRY_TYPE_VIRTUAL:
        store = _virtual_store(hass, entry)
        saved = (await store.async_load() or {}).get("message")
        board = VestaboardModel(COLOR_BLACK, entry.data[CONF_BOARD_MODEL])
        client = VestaboardVirtualClient(
            entry.title, board.rows, board.columns, message=saved
        )
    else:
        client = await create_client(hass, entry.data)
    coordinator = VestaboardCoordinator(hass, entry, client)
    if store is not None:
        _async_save_virtual_message(entry, coordinator, store, saved)
    await coordinator.async_config_entry_first_refresh()

    if not coordinator.data:
        raise ConfigEntryNotReady

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True


def _virtual_store(hass: HomeAssistant, entry: VestaboardConfigEntry) -> Store:
    """Return the store that keeps a virtual board's message across restarts."""
    return Store(hass, VIRTUAL_STORAGE_VERSION, f"{DOMAIN}.virtual_{entry.entry_id}")


@callback
def _async_save_virtual_message(
    entry: VestaboardConfigEntry,
    coordinator: VestaboardCoordinator,
    store: Store,
    saved: list[list[int]] | None,
) -> None:
    """Save a virtual board's persistent message whenever it changes.

    A temporary message showing at shutdown isn't saved, so the board comes
    back with its persistent message. Any pending save is written on unload,
    so a reload loads the latest message and a removal can't be undone by a
    late write.
    """
    latest = {"message": saved}

    @callback
    def _async_persistent_message_changed(message: list[list[int]]) -> None:
        if message == latest["message"]:
            return
        latest["message"] = message
        store.async_delay_save(lambda: {"message": message}, VIRTUAL_SAVE_DELAY)

    coordinator.on_persistent_message = _async_persistent_message_changed
    entry.async_on_unload(lambda: store.async_save(dict(latest)))


async def async_remove_entry(hass: HomeAssistant, entry: VestaboardConfigEntry) -> None:
    """Handle removal of a config entry."""
    if get_entry_type(entry) == ENTRY_TYPE_VIRTUAL:
        await _virtual_store(hass, entry).async_remove()


async def async_unload_entry(hass: HomeAssistant, entry: VestaboardConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await entry.runtime_data.vestaboard.close()
    return unload_ok


async def update_listener(hass: HomeAssistant, entry: VestaboardConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
