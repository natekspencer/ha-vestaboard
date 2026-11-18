"""Vestaboard coordinator."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime, time, timedelta
import logging
from typing import Any

from aiohttp import ClientConnectorError, ClientError, ClientResponseError

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
    CONF_HEART,
    CONF_LAYOUT,
    CONF_MODEL,
    CONF_QUIET_END,
    CONF_QUIET_HOURS,
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

# How long a board can go unread before its entities become unavailable.
# Network or Wi-Fi hiccups can fail the odd read, so a few failed polls keep the last state.
READ_FAILURE_GRACE = timedelta(minutes=1)

# Seconds to wait before each retry of a write the board refused to connect for.
# One retry covers a brief blip; longer outages fail with a clear error instead.
WRITE_RETRY_DELAYS = (1,)

REVERT_RETRY_DELAYS = (
    timedelta(seconds=30),
    timedelta(minutes=1),
    timedelta(minutes=2),
)
REVERT_RETRY_MAX_DELAY = timedelta(minutes=5)

# Coalesce member board updates (e.g. after writing to every board) into one refresh
ARRAY_REFRESH_COOLDOWN = 0.5


# Options the quiet hours entities change without reloading the entry
QUIET_HOURS_OPTIONS = (CONF_QUIET_HOURS, CONF_QUIET_START, CONF_QUIET_END)


def entry_reload_key(entry: ConfigEntry) -> tuple:
    """Return what an entry must be reloaded for if it changes.

    That's everything except quiet hours, which apply without a reload.
    """
    options = {
        key: value
        for key, value in entry.options.items()
        if key not in QUIET_HOURS_OPTIONS
    }
    return entry.title, dict(entry.data), options


def quiet_hours_enabled(options: Mapping[str, Any]) -> bool:
    """Return whether quiet hours are turned on.

    Before the quiet hours switch existed, quiet hours were on whenever start
    and end were set to different times.
    """
    if (enabled := options.get(CONF_QUIET_HOURS)) is not None:
        return enabled
    start, end = options.get(CONF_QUIET_START), options.get(CONF_QUIET_END)
    return bool(start and end and start != end)


def _in_quiet_hours(start: time | None, end: time | None) -> bool:
    """Check if the current time is within quiet hours.

    Equal start and end times mean quiet all day.
    """
    if start and end:
        now = dt_util.now().time()
        if start < end:
            return start <= now < end
        return start <= now or now < end
    return False


class WriteNotSent(HomeAssistantError):
    """A connection failure or explicit refusal proves no display was accepted."""


class WriteCancelledBeforeSend(asyncio.CancelledError):
    """Cancellation while backing off a refused connection, before sending."""


class QuietHoursMixin:
    """Quiet hours settings, shared by board and array coordinators."""

    quiet_start: time | None = None
    quiet_end: time | None = None
    quiet_hours_enabled: bool = False

    def apply_quiet_hours(self, options: Mapping[str, Any]) -> None:
        """Apply quiet hours settings from config entry options."""
        start, end = options.get(CONF_QUIET_START), options.get(CONF_QUIET_END)
        self.quiet_start = dt_util.parse_time(start) if start else None
        self.quiet_end = dt_util.parse_time(end) if end else None
        self.quiet_hours_enabled = quiet_hours_enabled(options)

    def _in_own_quiet_hours(self) -> bool:
        """Check if this coordinator's own quiet hours are active now."""
        return self.quiet_hours_enabled and _in_quiet_hours(
            self.quiet_start, self.quiet_end
        )


class VestaboardCoordinator(QuietHoursMixin, DataUpdateCoordinator):
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
    # Possibly delivered displays excluded from persistent capture after failed writes.
    _failed_revert_messages: tuple[list[list[int]], ...] = ()
    _revert_attempt: int = 0
    # Ignore a read begun before a newer write.
    _write_revision: int = 0
    _write_in_progress: bool = False
    # Called when the persistent message changes, e.g. to save it
    on_persistent_message: Callable[[list[list[int]]], None] | None = None

    # When reads started failing, if the last read failed
    _read_failing_since: datetime | None = None

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
        self.apply_quiet_hours(config_entry.options)
        self.reload_key = entry_reload_key(config_entry)

    @property
    def firmware_version(self) -> str | None:
        """Return the firmware version."""
        return self.vestaboard.firmware_version

    @property
    def default_transition_settings(self) -> dict[str, str | int]:
        """Return the default transition strategy settings."""
        return self.config_entry.options.get(CONF_STRATEGY) or {}

    def _prepare_data(self, data: list[list[int]]) -> tuple | None:
        """Render a snapshot without mutating coordinator state in the executor."""
        if data == self.data:
            return None
        model = self.model or VestaboardModel.from_color(
            self.model_color,
            data,
            has_frame=self.config_entry.options.get(CONF_SHOW_FRAME, True),
            has_heart=self.config_entry.options.get(CONF_HEART, False),
        )
        return (
            model,
            decode(data, model.emoji_map),
            create_png(data, self.model_color, model=model),
        )

    def _publish_render(
        self, data: list[list[int]], rendered: tuple | None
    ) -> list[list[int]]:
        """Commit an already validated render, without yielding."""
        if rendered is not None:
            self.model, self.message, self.image = rendered
            self.last_updated = dt_util.now()
        return data

    @property
    def revert_retry_pending(self) -> bool:
        """Whether the expiration is recovery backoff, not an alert lifetime."""
        return self._revert_attempt > 0

    def quiet_hours(self) -> bool:
        """Check if quiet hours."""
        return self._in_own_quiet_hours()

    async def _async_update_data(self):
        """Fetch data from Vestaboard."""
        revision = self._write_revision
        read_during_write = self._write_in_progress
        try:
            async with asyncio.timeout(10):
                data = await self.vestaboard.read_message()
        except InvalidApiKeyError as err:
            raise ConfigEntryAuthFailed from err
        except (ClientError, TimeoutError) as ex:
            return self._handle_read_failure(ex)
        if data is None:
            raise ConfigEntryAuthFailed
        if self._read_failing_since is not None:
            _LOGGER.debug("Reading %s recovered", self.vestaboard.base_url)
            self._read_failing_since = None

        def stale():
            return (
                read_during_write
                or revision != self._write_revision
                or self._write_in_progress
            )

        def superseded():
            if self.data is None:
                raise UpdateFailed("Read superseded by a write; waiting for fresh data")
            return self.data

        if stale():
            return superseded()
        # Rendering is pure and outside the lock. Revalidate before committing
        # either the render or persistent/recovery state after this await.
        rendered = await self.hass.async_add_executor_job(self._prepare_data, data)
        async with self._temporary_message_lock:
            if stale():
                return superseded()
            if self._failed_revert_messages:
                if (
                    data == self.persistent_message
                    or data not in self._failed_revert_messages
                ):
                    self._settle_recovery()
                    if data != self.persistent_message:
                        self._set_persistent_message(data)
                else:
                    self._failed_revert_messages = (data,)
            if (
                self.temporary_message_expiration is None
                and not self._failed_revert_messages
            ):
                self._set_persistent_message(data)
            return self._publish_render(data, rendered)

    def _settle_recovery(self) -> None:
        """Resolve uncertainty without cancelling an expired parent handoff."""
        if (
            self._restore_after
            and self.temporary_message_expiration
            and self.temporary_message_expiration <= dt_util.now()
        ):
            self._failed_revert_messages = ()
            self._revert_attempt = 0
        else:
            self._clear_temporary_state()

    def _handle_read_failure(self, ex: Exception) -> list[list[int]]:
        """Keep the last state through a short run of failed reads.

        Raises UpdateFailed, making entities unavailable, once reads have
        failed for longer than READ_FAILURE_GRACE, or if there's no state yet.
        """
        now = dt_util.utcnow()
        if self._read_failing_since is None:
            self._read_failing_since = now
        if (
            self.data is not None
            and now - self._read_failing_since < READ_FAILURE_GRACE
        ):
            _LOGGER.debug(
                "Couldn't read vestaboard at %s, keeping the last state: %r",
                self.vestaboard.base_url,
                ex,
            )
            return self.data
        raise UpdateFailed(
            f"Couldn't read vestaboard at {self.vestaboard.base_url}"
        ) from ex

    async def write_and_update_state(
        self, json: dict[str, list[list[int]] | str | int]
    ) -> None:
        """Write to board and immediately update coordinator."""
        self._write_revision += 1
        self._write_in_progress = True
        try:
            if not await self._async_write_with_retry(json):
                # The client only reports non-201 here, not a definite refusal.
                raise HomeAssistantError(
                    f"Vestaboard at {self.vestaboard.base_url} didn't accept the message"
                )
            rendered = await self.hass.async_add_executor_job(
                self._prepare_data, json["characters"]
            )
            self.async_set_updated_data(
                self._publish_render(json["characters"], rendered)
            )
        finally:
            self._write_in_progress = False
            self._write_revision += 1

    async def _async_write_with_retry(
        self, json: dict[str, list[list[int]] | str | int]
    ) -> bool:
        """Write to the board, retrying while it refuses or can't take connections.

        Only failures to connect are retried: the message was never sent, so
        retrying can't show it twice. Other errors are raised straight away.
        """
        url = self.vestaboard.base_url
        delays = iter(WRITE_RETRY_DELAYS)
        attempt = 0
        while True:
            attempt += 1
            try:
                return await self.vestaboard.write_message(json)
            except ClientConnectorError as err:
                if (delay := next(delays, None)) is None:
                    raise WriteNotSent(
                        f"Couldn't connect to Vestaboard at {url} after "
                        f"{attempt} attempts: {err}"
                    ) from err
                _LOGGER.debug(
                    "Couldn't connect to %s (attempt %s), retrying in %ss: %r",
                    url,
                    attempt,
                    delay,
                    err,
                )
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError as err:
                    raise WriteCancelledBeforeSend from err
            except ClientResponseError as err:
                # Explicit request rejection, unlike a lost acknowledgement or
                # arbitrary non-201 response, proves no display was accepted.
                error_type = (
                    WriteNotSent
                    if err.status in (400, 401, 403, 404, 413, 422)
                    else HomeAssistantError
                )
                raise error_type(
                    f"Couldn't write message to Vestaboard at {url}: {err!r}"
                ) from err
            except (ClientError, TimeoutError) as err:
                raise HomeAssistantError(
                    f"Couldn't write message to Vestaboard at {url}: {err!r}"
                ) from err

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
                await self._async_write_temporary_message(
                    json, expiration, restore_after
                )
            else:
                self._set_persistent_message(json["characters"])
                current = self.temporary_message_expiration
                if not (current and current > dt_util.now()):
                    await self._async_revert_to_persistent_message(
                        preserve_parent=bool(current and self._restore_after)
                    )

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
            if (expiration and expiration > dt_util.now()) or (
                expiration is None and self._failed_revert_messages
            ):
                await self._async_revert_to_persistent_message()

    async def _async_write_temporary_message(
        self,
        json: dict[str, list[list[int]] | str | int],
        expiration: datetime,
        restore_after: tuple[list[list[int]], datetime] | None = None,
    ) -> None:
        """Write a temporary message and schedule its expiration.

        Must be called with the temporary message lock held.
        """
        previous = self.temporary_message_expiration
        self.temporary_message_expiration = expiration
        try:
            await self.write_and_update_state(json)
        except (WriteNotSent, WriteCancelledBeforeSend):
            self.temporary_message_expiration = previous
            raise
        except (Exception, asyncio.CancelledError):
            if previous or self._failed_revert_messages:
                self._remember_display(self.data)
            self._remember_display(json["characters"])
            # An uncertain alert retains the requested lifetime and parent.
            self._restore_after = restore_after
            self._revert_attempt = 0
            self._arm_expiration(expiration)
            raise
        self._failed_revert_messages = ()
        self._restore_after = restore_after
        self._revert_attempt = 0
        self._arm_expiration(expiration)

    def _remember_display(self, display: list[list[int]] | None) -> None:
        """Exclude a possibly delivered alert from persistent capture."""
        if display is not None and display not in self._failed_revert_messages:
            self._failed_revert_messages += (display,)

    def _arm_expiration(self, expiration: datetime) -> None:
        """Replace the timer, also when a cancelled operation retains recovery."""
        if self._cancel_cb:
            self._cancel_cb()
        self.temporary_message_expiration = expiration
        self._cancel_cb = async_track_point_in_time(
            self.hass, self._handle_temporary_message_expiration, expiration
        )
        self.async_update_listeners()

    async def _handle_temporary_message_expiration(self, now: datetime) -> None:
        """Handle temporary message expiration."""
        async with self._temporary_message_lock:
            expiration = self.temporary_message_expiration
            if expiration is None or expiration > now:
                # Already cleared, or a newer temporary message replaced this one
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
                else:
                    self._restore_after = None
                    return
            _LOGGER.debug(
                "Vestaboard temporary message expired @ %s, reverting to persistent message",
                now,
            )
            try:
                await self._async_revert_to_persistent_message()
            except Exception:
                _LOGGER.warning(
                    "Unable to restore the persistent message; timer retry scheduled",
                    exc_info=True,
                )

    async def _async_revert_to_persistent_message(
        self, preserve_parent: bool = False
    ) -> None:
        """One failure path for explicit writes, clears and timer restoration."""
        displays = self._failed_revert_messages
        if (
            self.temporary_message_expiration
            and self.data is not None
            and self.data not in displays
        ):
            displays += (self.data,)
        target = self.persistent_message
        attempt = self._revert_attempt
        expiration, parent = self.temporary_message_expiration, self._restore_after
        if preserve_parent:
            self._failed_revert_messages = ()
            self._revert_attempt = 0
        else:
            self._clear_temporary_state()
        try:
            if target is not None:
                await self.write_and_update_state(
                    {"characters": target, **self.default_transition_settings}
                )
        except (Exception, asyncio.CancelledError) as err:
            self._failed_revert_messages = displays
            # Only an actual possibly delivered target belongs in uncertainty.
            # Queuing a new persistent value does not add the superseded value.
            if not isinstance(err, (WriteNotSent, WriteCancelledBeforeSend)):
                self._remember_display(target)
            self._revert_attempt = attempt
            if preserve_parent:
                self._restore_after = parent
                self._arm_expiration(expiration)
            elif displays:
                # Even an unsent revert must retry: the prior alert is stranded.
                self._schedule_revert_retry()
            raise

    @callback
    def _schedule_revert_retry(self) -> None:
        """Retry via the existing expiration path, never from a poll."""
        delay = (
            REVERT_RETRY_DELAYS[self._revert_attempt]
            if self._revert_attempt < len(REVERT_RETRY_DELAYS)
            else REVERT_RETRY_MAX_DELAY
        )
        self._revert_attempt += 1
        self._arm_expiration(dt_util.now() + delay)

    @callback
    def _clear_temporary_state(self) -> None:
        """Discard expiration and recovery state after clearing or superseding it."""
        self.temporary_message_expiration = None
        if self._cancel_cb:
            self._cancel_cb()
            self._cancel_cb = None
        self._restore_after = None
        self._failed_revert_messages = ()
        self._revert_attempt = 0


class VestaboardArrayCoordinator(
    QuietHoursMixin, DataUpdateCoordinator[list[list[int]]]
):
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
        self.apply_quiet_hours(config_entry.options)
        self.reload_key = entry_reload_key(config_entry)
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
        if self._in_own_quiet_hours():
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
            self.message = decode(data, self.model.emoji_map)
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
