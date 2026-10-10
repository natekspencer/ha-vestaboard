"""Support for Vestaboard."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .client import VestaboardVirtualClient
from .const import (
    COLOR_BLACK,
    CONF_BOARD_MODEL,
    CONF_LAYOUT,
    DATA_HASS_CONFIG,
    DOMAIN,
    ENTRY_TYPE_ARRAY,
    ENTRY_TYPE_VIRTUAL,
)
from .coordinator import (
    VestaboardArrayCoordinator,
    VestaboardConfigEntry,
    VestaboardCoordinator,
    entry_reload_key,
)
from .helpers import create_client, get_entry_type, is_array_entry
from .repairs import (
    ISSUE_ARRAY_BOARD_DISABLED,
    ISSUE_ARRAY_MISSING_BOARD,
    array_issue_id,
)
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
    Platform.SWITCH,
    Platform.TIME,
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Vestaboard integration."""
    async_setup_services(hass)
    hass.data[DOMAIN] = {DATA_HASS_CONFIG: config}
    return True


async def async_setup_entry(hass: HomeAssistant, entry: VestaboardConfigEntry) -> bool:
    """Set up Vestaboard from a config entry."""
    entry_type = get_entry_type(entry)
    if entry_type == ENTRY_TYPE_ARRAY:
        return await _async_setup_array_entry(hass, entry)

    store = None
    if entry_type == ENTRY_TYPE_VIRTUAL:
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

    @callback
    def _async_on_state_change() -> None:
        if entry.state is ConfigEntryState.LOADED:
            _async_reload_arrays_with_member(hass, entry.entry_id)

    entry.async_on_unload(entry.async_on_state_change(_async_on_state_change))

    return True


async def _async_setup_array_entry(
    hass: HomeAssistant, entry: VestaboardConfigEntry
) -> bool:
    """Set up a Vestaboard array from a config entry."""
    coordinator = VestaboardArrayCoordinator(hass, entry)
    members = [
        hass.config_entries.async_get_entry(entry_id)
        for entry_id in coordinator.member_entry_ids
    ]
    if None in members:
        _async_create_array_issue(hass, entry, ISSUE_ARRAY_MISSING_BOARD)
        raise ConfigEntryError(
            "A Vestaboard in this array has been deleted. "
            "Reconfigure or delete this array."
        )
    if disabled := [member.title for member in members if member.disabled_by]:
        boards = ", ".join(disabled)
        _async_create_array_issue(
            hass, entry, ISSUE_ARRAY_BOARD_DISABLED, {"boards": boards}
        )
        raise ConfigEntryError(
            f"{boards} in this array is disabled. "
            "Enable it, or reconfigure or delete this array."
        )
    for member in members:
        if member.state is not ConfigEntryState.LOADED:
            raise ConfigEntryNotReady(f"Waiting for Vestaboard {member.title}")

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    coordinator.async_setup_member_listeners()
    _async_delete_array_issues(hass, entry)

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


@callback
def _async_reload_arrays_with_member(hass: HomeAssistant, entry_id: str) -> None:
    """Reload arrays containing this board so they use its new coordinator."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if (
            is_array_entry(entry)
            and entry.state
            in (
                ConfigEntryState.LOADED,
                ConfigEntryState.SETUP_IN_PROGRESS,
                ConfigEntryState.SETUP_RETRY,
                # Failed setup because this board was disabled
                ConfigEntryState.SETUP_ERROR,
            )
            and any(entry_id in row for row in entry.data[CONF_LAYOUT])
        ):
            hass.config_entries.async_schedule_reload(entry.entry_id)


@callback
def _async_create_array_issue(
    hass: HomeAssistant,
    entry: VestaboardConfigEntry,
    issue: str,
    placeholders: dict[str, str] | None = None,
) -> None:
    """Raise a fixable repair issue for an array that can't be set up."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        array_issue_id(issue, entry.entry_id),
        is_fixable=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key=issue,
        data={"entry_id": entry.entry_id},
        translation_placeholders={"array": entry.title, **(placeholders or {})},
    )


@callback
def _async_delete_array_issues(
    hass: HomeAssistant, entry: VestaboardConfigEntry
) -> None:
    """Delete an array's repair issues."""
    for issue in (ISSUE_ARRAY_MISSING_BOARD, ISSUE_ARRAY_BOARD_DISABLED):
        ir.async_delete_issue(hass, DOMAIN, array_issue_id(issue, entry.entry_id))


async def async_remove_entry(hass: HomeAssistant, entry: VestaboardConfigEntry) -> None:
    """Handle removal of a config entry."""
    if is_array_entry(entry):
        _async_delete_array_issues(hass, entry)
        return

    if get_entry_type(entry) == ENTRY_TYPE_VIRTUAL:
        await _virtual_store(hass, entry).async_remove()

    # The board is already gone, so reloading its arrays makes them fail setup
    # and raise a repair issue rather than keep showing the board's last state
    for array in hass.config_entries.async_entries(DOMAIN):
        if is_array_entry(array) and any(
            entry.entry_id in row for row in array.data[CONF_LAYOUT]
        ):
            hass.config_entries.async_schedule_reload(array.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: VestaboardConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not is_array_entry(entry):
        await entry.runtime_data.vestaboard.close()
    return unload_ok


async def update_listener(hass: HomeAssistant, entry: VestaboardConfigEntry) -> None:
    """Handle options update.

    Quiet hours changes, e.g. from the quiet hours entities, apply without a
    reload; anything else reloads the entry.
    """
    coordinator = entry.runtime_data
    if entry_reload_key(entry) == coordinator.reload_key:
        coordinator.apply_quiet_hours(entry.options)
        coordinator.async_update_listeners()
        return
    await hass.config_entries.async_reload(entry.entry_id)
