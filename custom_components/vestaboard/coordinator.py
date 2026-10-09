"""Vestaboard coordinator."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, time, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import homeassistant.util.dt as dt_util

from .client import InvalidApiKeyError, VestaboardLocalClient, VestaboardVirtualClient
from .const import (
    COLOR_BLACK,
    CONF_MODEL,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_SHOW_FRAME,
    CONF_STRATEGY,
    DOMAIN,
)
from .helpers import create_png, decode
from .vestaboard_model import VestaboardModel

_LOGGER = logging.getLogger(__name__)

type VestaboardConfigEntry = ConfigEntry[VestaboardCoordinator]


def _parse_quiet_hours(options: dict) -> tuple[time | None, time | None]:
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
    ) -> None:
        """Write a persistent message, or a temporary one if expiration is set.

        A persistent message written while a temporary message is showing is
        held until the temporary message expires.
        """
        async with self._temporary_message_lock:
            if expiration:
                # Set before writing, so a refresh during the write doesn't take
                # the temporary message as the persistent one; restore on failure
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

    async def _handle_temporary_message_expiration(self, now: datetime) -> None:
        """Handle temporary message expiration."""
        async with self._temporary_message_lock:
            expiration = self.temporary_message_expiration
            if expiration and expiration > now:
                # A newer temporary message replaced this one while waiting
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
        if rows := self.persistent_message:
            await self.write_and_update_state(
                {"characters": rows, **self.default_transition_settings}
            )
