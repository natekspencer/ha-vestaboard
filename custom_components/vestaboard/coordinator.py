"""Vestaboard coordinator."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, time, timedelta
import logging

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import homeassistant.util.dt as dt_util

from .client import InvalidApiKeyError, VestaboardLocalClient, VestaboardVirtualClient
from .const import (
    COLOR_BLACK,
    CONF_LAYOUT,
    CONF_MODEL,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_SHOW_FRAME,
    CONF_STRATEGY,
    DOMAIN,
)
from .helpers import create_framed_array_png, create_png, decode
from .vestaboard_model import VestaboardArrayModel, VestaboardModel

_LOGGER = logging.getLogger(__name__)

type VestaboardConfigEntry = ConfigEntry[
    VestaboardCoordinator | VestaboardArrayCoordinator
]

# Coalesce member board updates (e.g. after writing to every board) into one refresh
ARRAY_REFRESH_COOLDOWN = 0.5


def _parse_quiet_hours(
    options: dict,
) -> tuple[time | None, time | None]:
    """Parse quiet hours start and end from config entry options."""
    if (start := options.get(CONF_QUIET_START)) != (end := options.get(CONF_QUIET_END)):
        return dt_util.parse_time(start), dt_util.parse_time(end)
    return None, None


def _in_quiet_hours(start: time | None, end: time | None) -> bool:
    """Check if the current time is within quiet hours."""
    if start and end:
        now = dt_util.now().time()
        if start < end:
            return start <= now < end
        return start <= now or now < end
    return False


class VestaboardCoordinator(DataUpdateCoordinator):
    """Vestaboard data update coordinator."""

    config_entry: VestaboardConfigEntry

    data: list[list[int]] | None
    last_updated: datetime | None = None
    message: str | None
    image: bytes | None
    persistent_message: list[list[int]] | None = None
    temporary_message_expiration: datetime | None = None
    _cancel_cb: CALLBACK_TYPE | None = None
    # A temporary message to show again when the current one expires
    _restore_after: tuple[list[list[int]], datetime] | None = None
    # Called when the persistent message changes, e.g. to save it
    on_persistent_message: Callable[[list[list[int]]], None] | None = None

    _read_errors: int = 0

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: VestaboardConfigEntry,
        vestaboard: VestaboardLocalClient | VestaboardVirtualClient,
    ) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=15),
        )
        self.vestaboard = vestaboard
        # Serializes temporary message writes, expirations and clears
        self._temporary_message_lock = asyncio.Lock()

        self.model: VestaboardModel | None = None
        self.model_color = config_entry.options.get(CONF_MODEL, COLOR_BLACK)
        self.quiet_start, self.quiet_end = _parse_quiet_hours(config_entry.options)

    @property
    def firmware_version(self) -> str | None:
        """Return the firmware version."""
        return self.vestaboard.firmware_version

    @property
    def default_transition_settings(self) -> dict[str, str | int]:
        """Return the default transition strategy settings."""
        return self.config_entry.options.get(CONF_STRATEGY) or {}

    def process_data(self, data: list[list[int]]) -> list[list[int]]:
        """Process data."""
        if data != self.data:
            if self.model is None:
                self.model = VestaboardModel.from_color(
                    self.model_color,
                    data,
                    has_frame=self.config_entry.options.get(CONF_SHOW_FRAME, True),
                )
            self.last_updated = dt_util.now()
            self.message = decode(data)
            self.image = create_png(data, self.model_color, model=self.model)
        return data

    def quiet_hours(self) -> bool:
        """Check if quiet hours."""
        return _in_quiet_hours(self.quiet_start, self.quiet_end)

    async def _async_update_data(self):
        """Fetch data from Vestaboard."""
        try:
            async with asyncio.timeout(10):
                data = await self.vestaboard.read_message()
        except InvalidApiKeyError as err:
            raise ConfigEntryAuthFailed from err
        except Exception as ex:
            raise UpdateFailed(
                f"Couldn't read vestaboard at {self.vestaboard.base_url}"
            ) from ex
        if data is None:
            raise ConfigEntryAuthFailed

        if self.temporary_message_expiration is None:
            self._set_persistent_message(data)

        return await self.hass.async_add_executor_job(self.process_data, data)

    async def write_and_update_state(
        self, json: dict[str, list[list[int]] | str | int]
    ) -> None:
        """Write to board and immediately update coordinator."""
        if not await self.vestaboard.write_message(json):
            raise UpdateFailed(f"Failed to write message to {self.name}")

        # Manually update coordinator state for instant UI feedback
        data = await self.hass.async_add_executor_job(
            self.process_data, json["characters"]
        )
        self.async_set_updated_data(data)

    async def async_write_message(
        self,
        json: dict[str, list[list[int]] | str | int],
        expiration: datetime | None = None,
        restore_after: tuple[list[list[int]], datetime] | None = None,
    ) -> None:
        """Write a persistent message, or a temporary one if expiration is set.

        A persistent message written while a temporary message is showing is
        held until the temporary message expires. A temporary message may pass
        restore_after, a temporary message (characters and expiration) to show
        again when it expires, if that hasn't expired by then.
        """
        async with self._temporary_message_lock:
            if expiration:
                await self._async_write_temporary_message(json, expiration)
                self._restore_after = restore_after
            else:
                self._set_persistent_message(json["characters"])
                current = self.temporary_message_expiration
                if not (current and current > dt_util.now()):
                    await self.write_and_update_state(json)

    def _set_persistent_message(self, rows: list[list[int]]) -> None:
        """Set the persistent message, notifying if it changed."""
        changed = rows != self.persistent_message
        self.persistent_message = rows
        if changed and self.on_persistent_message:
            self.on_persistent_message(rows)

    async def async_clear_temporary_message(self) -> None:
        """Clear an active temporary message, reverting to the persistent message."""
        async with self._temporary_message_lock:
            expiration = self.temporary_message_expiration
            if expiration and expiration > dt_util.now():
                await self._async_revert_to_persistent_message()

    async def _async_write_temporary_message(
        self, json: dict[str, list[list[int]] | str | int], expiration: datetime
    ) -> None:
        """Write a temporary message and schedule its expiration.

        Must be called with the temporary message lock held.
        """
        # Set before writing, so a refresh during the write doesn't take the
        # temporary message as the persistent one; restore on failure
        previous = self.temporary_message_expiration
        self.temporary_message_expiration = expiration
        try:
            await self.write_and_update_state(json)
        except Exception:
            self.temporary_message_expiration = previous
            raise
        if self._cancel_cb:
            self._cancel_cb()
        self._cancel_cb = async_track_point_in_time(
            self.hass, self._handle_temporary_message_expiration, expiration
        )

    async def _handle_temporary_message_expiration(self, now: datetime) -> None:
        """Handle temporary message expiration."""
        async with self._temporary_message_lock:
            expiration = self.temporary_message_expiration
            if expiration and expiration > now:
                # A newer temporary message replaced this one while waiting
                return
            if (restore := self._restore_after) and restore[1] > now:
                characters, restore_expiration = restore
                try:
                    await self._async_write_temporary_message(
                        {"characters": characters}, restore_expiration
                    )
                except Exception:
                    # Don't leave the expired message showing
                    _LOGGER.warning(
                        "Unable to restore the previous temporary message, "
                        "reverting to the persistent message",
                        exc_info=True,
                    )
                    await self._async_revert_to_persistent_message()
                    return
                self._restore_after = None
                return
            _LOGGER.debug(
                "Vestaboard temporary message expired @ %s, reverting to persistent message",
                now,
            )
            await self._async_revert_to_persistent_message()

    async def _async_revert_to_persistent_message(self) -> None:
        """Replace the temporary message with the persistent message.

        Must be called with the temporary message lock held.
        """
        if self._cancel_cb:
            self._cancel_cb()
            self._cancel_cb = None
        self.temporary_message_expiration = None
        self._restore_after = None
        if rows := self.persistent_message:
            await self.write_and_update_state(
                {"characters": rows, **self.default_transition_settings}
            )


class VestaboardArrayCoordinator(DataUpdateCoordinator[list[list[int]]]):
    """Coordinator for a grid of Vestaboards acting as one larger virtual board.

    The array holds no connection of its own. It references the config entries
    of its member boards and reads from/writes to them via their coordinators.
    """

    config_entry: VestaboardConfigEntry

    last_updated: datetime | None = None
    message: str | None = None
    image: bytes | None = None

    def __init__(
        self, hass: HomeAssistant, config_entry: VestaboardConfigEntry
    ) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}_array",
            update_interval=None,
            request_refresh_debouncer=Debouncer(
                hass, _LOGGER, cooldown=ARRAY_REFRESH_COOLDOWN, immediate=False
            ),
        )
        self.layout: list[list[str]] = config_entry.data[CONF_LAYOUT]
        self.quiet_start, self.quiet_end = _parse_quiet_hours(config_entry.options)
        self.model: VestaboardArrayModel | None = None

    @property
    def member_entry_ids(self) -> list[str]:
        """Return the config entry ids of every member board."""
        return [entry_id for row in self.layout for entry_id in row]

    @property
    def firmware_version(self) -> str | None:
        """Return the firmware version."""
        return None

    @property
    def default_transition_settings(self) -> dict[str, str | int]:
        """Return the default transition strategy settings."""
        return self.config_entry.options.get(CONF_STRATEGY) or {}

    @property
    def temporary_message_expiration(self) -> datetime | None:
        """Return the latest temporary message expiration across member boards."""
        try:
            members = self.members()
        except HomeAssistantError:
            return None
        expirations = [
            expiration
            for row in members
            for member in row
            if (expiration := member.temporary_message_expiration)
        ]
        return max(expirations, default=None)

    def members(self) -> list[list[VestaboardCoordinator]]:
        """Return the member board coordinators in grid layout.

        Members are looked up on every call so that a reloaded member board
        is always referenced by its current coordinator.
        """
        grid: list[list[VestaboardCoordinator]] = []
        for row in self.layout:
            grid_row: list[VestaboardCoordinator] = []
            for entry_id in row:
                entry = self.hass.config_entries.async_get_entry(entry_id)
                if entry is None or entry.state is not ConfigEntryState.LOADED:
                    name = entry.title if entry else entry_id
                    raise HomeAssistantError(
                        f"Vestaboard {name} in array {self.config_entry.title} is not available"
                    )
                grid_row.append(entry.runtime_data)
            grid.append(grid_row)
        return grid

    def _member_reloading(self) -> bool:
        """Return True if any member board is part way through a reload."""
        for entry_id in self.member_entry_ids:
            if (entry := self.hass.config_entries.async_get_entry(entry_id)) is None:
                continue
            if entry.state in (
                ConfigEntryState.UNLOAD_IN_PROGRESS,
                ConfigEntryState.SETUP_IN_PROGRESS,
            ):
                return True
            if entry.state is ConfigEntryState.NOT_LOADED and not entry.disabled_by:
                return True
        return False

    @callback
    def async_setup_member_listeners(self) -> None:
        """Refresh the array whenever any member board updates."""

        @callback
        def _handle_member_update() -> None:
            # A member that is unloading will trigger an array reload once it's back
            try:
                self.members()
            except HomeAssistantError:
                return
            self.config_entry.async_create_background_task(
                self.hass, self.async_request_refresh(), "vestaboard_array_refresh"
            )

        for row in self.members():
            for member in row:
                self.config_entry.async_on_unload(
                    member.async_add_listener(_handle_member_update)
                )

        @callback
        def _handle_member_state_change() -> None:
            # Reload if a member was disabled, so setup raises a repair issue.
            # Otherwise refresh, which marks the array unavailable if a member
            # failed; a member that is reloading or deleted reloads the array.
            if any(
                (member_entry := self.hass.config_entries.async_get_entry(entry_id))
                and member_entry.disabled_by
                for entry_id in self.member_entry_ids
            ):
                self.hass.config_entries.async_schedule_reload(
                    self.config_entry.entry_id
                )
                return
            self.config_entry.async_create_background_task(
                self.hass, self.async_request_refresh(), "vestaboard_array_refresh"
            )

        for entry_id in self.member_entry_ids:
            if member_entry := self.hass.config_entries.async_get_entry(entry_id):
                self.config_entry.async_on_unload(
                    member_entry.async_on_state_change(_handle_member_state_change)
                )

    def quiet_hours(self) -> bool:
        """Check if quiet hours for the array or any of its loaded member boards."""
        if _in_quiet_hours(self.quiet_start, self.quiet_end):
            return True
        for entry_id in self.member_entry_ids:
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if (
                entry is not None
                and entry.state is ConfigEntryState.LOADED
                and entry.runtime_data.quiet_hours()
            ):
                return True
        return False

    def process_data(self, data: list[list[int]]) -> list[list[int]]:
        """Process data."""
        if data != self.data:
            self.last_updated = dt_util.now()
            self.message = decode(data)
            if self.config_entry.options.get(CONF_SHOW_FRAME, False):
                self.image = create_framed_array_png(
                    self.model.split(data), self.model.colors
                )
            else:
                self.image = create_png(data, model=self.model)
        return data

    async def _async_update_data(self) -> list[list[int]]:
        """Combine the current data of every member board."""
        try:
            members = self.members()
        except HomeAssistantError as err:
            if self.data is not None and self._member_reloading():
                # The array is reloaded once the member is back, so hold the last state
                return self.data
            raise UpdateFailed(str(err)) from err

        if self.model is None:
            board = members[0][0].model
            if board is None:
                raise UpdateFailed("Vestaboard model is not initialized")
            # Each board keeps its own color; a member's color change reloads it,
            # which reloads the array and picks up the new color here
            self.model = VestaboardArrayModel(
                board.model,
                tuple(tuple(member.model_color for member in row) for row in members),
            )

        data = self.model.join([[member.data for member in row] for row in members])
        return await self.hass.async_add_executor_job(self.process_data, data)

    async def async_write_message(
        self,
        json: dict[str, list[list[int]] | str | int],
        expiration: datetime | None = None,
    ) -> None:
        """Split a message across the member boards and write to all at once."""
        members = self.members()
        tiles = self.model.split(json["characters"])
        await asyncio.gather(
            *(
                member.async_write_message({**json, "characters": tile}, expiration)
                for member_row, tile_row in zip(members, tiles)
                for member, tile in zip(member_row, tile_row)
            )
        )

    async def async_clear_temporary_message(self) -> None:
        """Clear active temporary messages on every member board."""
        await asyncio.gather(
            *(
                member.async_clear_temporary_message()
                for row in self.members()
                for member in row
            )
        )
