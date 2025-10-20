"""Vestaboard coordinator."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

import async_timeout
import httpx
from vesta import LocalClient
from vesta.chars import Rows

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import homeassistant.util.dt as dt_util

from .const import COLOR_BLACK, CONF_MODEL, CONF_QUIET_END, CONF_QUIET_START, DOMAIN
from .helpers import create_png, decode
from .vestaboard_model import VestaboardModel

_LOGGER = logging.getLogger(__name__)

type VestaboardConfigEntry = ConfigEntry[VestaboardCoordinator]


def write_message(self: LocalClient, json: dict[str, Rows | str | int]) -> bool:
    """Write a message to the Vestaboard.

    `json` must be a json object and may contain:
      - `characters` - a 6x22 array of character codes
      - `strategy` - column
      - `step_interval_ms` - step interval in milliseconds
      - `step_size` - number of columns to animate

    :raises ValueError: if ``characters`` is a list with unsupported dimensions
    """
    if not self.enabled:
        raise RuntimeError("Local API has not been enabled")
    r = self.http.post("/local-api/message", json=json)
    r.raise_for_status()
    return r.status_code == httpx.codes.CREATED


LocalClient.write_message = write_message


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

    _read_errors: int = 0

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: VestaboardConfigEntry,
        vestaboard: LocalClient,
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

        self.model: VestaboardModel | None = None
        self.model_color = config_entry.options.get(CONF_MODEL, COLOR_BLACK)
        if (start := config_entry.options.get(CONF_QUIET_START)) != (
            end := config_entry.options.get(CONF_QUIET_END)
        ):
            self.quiet_start = dt_util.parse_time(start)
            self.quiet_end = dt_util.parse_time(end)
        else:
            self.quiet_start = self.quiet_end = None

    def process_data(self, data: list[list[int]]) -> list[list[int]]:
        """Process data."""
        if data != self.data:
            if self.model is None:
                self.model = VestaboardModel.from_color(self.model_color, data)
            self.last_updated = dt_util.now()
            self.message = decode(data)
            self.image = create_png(data, self.model_color)
        return data

    def quiet_hours(self) -> bool:
        """Check if quiet hours."""
        if self.quiet_start and self.quiet_end:
            now = dt_util.now().time()
            if self.quiet_start < self.quiet_end:
                return self.quiet_start <= now < self.quiet_end
            return self.quiet_start <= now or now < self.quiet_end
        return False

    async def _async_update_data(self):
        """Fetch data from Vestaboard."""
        try:
            async with async_timeout.timeout(10):
                data = await self.hass.async_add_executor_job(
                    self.vestaboard.read_message
                )
        except Exception as ex:
            raise UpdateFailed(
                f"Couldn't read vestaboard at {self.vestaboard.http.base_url.host}"
            ) from ex
        if data is None:
            raise ConfigEntryAuthFailed

        if self.persistent_message is None:
            self.persistent_message = data

        return await self.hass.async_add_executor_job(self.process_data, data)

    async def write_and_update_state(self, json: dict[str, Rows | str | int]) -> None:
        """Write to board and immediately update coordinator."""
        await self.hass.async_add_executor_job(self.vestaboard.write_message, json)
        # Manually update coordinator state for instant UI feedback
        self.async_set_updated_data(self.process_data(json["characters"]))

    async def _handle_temporary_message_expiration(self, now: datetime) -> None:
        """Handle temporary message expiration."""
        _LOGGER.debug(
            "Vestaboard temporary message expired @ %s, reverting to persistent message",
            now,
        )
        self.temporary_message_expiration = None
        if rows := self.persistent_message:
            await self.write_and_update_state({"characters": rows})
        if self._cancel_cb:
            self._cancel_cb()
            self._cancel_cb = None
