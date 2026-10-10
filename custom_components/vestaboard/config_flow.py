"""Config flow for Vestaboard integration."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any

from aiohttp import ClientConnectorError
import voluptuous as vol

from homeassistant.components import dhcp
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
)
from homeassistant.const import (
    ATTR_ENTITY_PICTURE,
    CONF_API_KEY,
    CONF_HOST,
    CONF_NAME,
    Platform,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult, section
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaCommonFlowHandler,
    SchemaFlowFormStep,
    SchemaOptionsFlowHandler,
)
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)
import homeassistant.util.dt as dt_util

from .client import EndpointStatus
from .const import (
    ALIGN_CENTER,
    COLOR_BLACK,
    COLOR_WHITE,
    CONF_ALIGN,
    CONF_ARRANGEMENT,
    CONF_BOARD,
    CONF_BOARD_MODEL,
    CONF_ENABLEMENT_TOKEN,
    CONF_ENTRY_TYPE,
    CONF_HEART,
    CONF_IDENTIFY,
    CONF_JUSTIFY,
    CONF_LAYOUT,
    CONF_MODEL,
    CONF_SHOW_FRAME,
    CONF_STEP_INTERVAL_MS,
    CONF_STEP_SIZE,
    CONF_STRATEGY,
    CONF_TRANSITIONS,
    DOMAIN,
    ENTRY_TYPE_ARRAY,
    ENTRY_TYPE_DEVICE,
    ENTRY_TYPE_VIRTUAL,
)
from .helpers import create_client, get_entry_type, is_array_entry
from .vestaboard_model import MODEL_FLAGSHIP, MODEL_NOTE, VestaboardModel

_LOGGER = logging.getLogger(__name__)

STEP_API_KEY_SCHEMA = vol.Schema(
    {vol.Required(CONF_API_KEY): str, vol.Optional(CONF_ENABLEMENT_TOKEN): bool}
)
STEP_USER_DATA_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str}).extend(
    STEP_API_KEY_SCHEMA.schema
)
STEP_VIRTUAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME, default="Virtual Vestaboard"): str,
        vol.Required(CONF_BOARD_MODEL, default=MODEL_FLAGSHIP): SelectSelector(
            SelectSelectorConfig(
                options=[MODEL_FLAGSHIP, MODEL_NOTE],
                translation_key=CONF_BOARD_MODEL,
            )
        ),
    }
)
COLOR_SCHEMA = vol.In({COLOR_BLACK: "Black", COLOR_WHITE: "White"})
OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MODEL, default=COLOR_BLACK): COLOR_SCHEMA,
        vol.Optional(CONF_STRATEGY): section(
            vol.Schema(
                {
                    vol.Required(CONF_STRATEGY): vol.In(CONF_TRANSITIONS),
                    vol.Optional(CONF_STEP_SIZE): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=132,
                            step=1,
                            unit_of_measurement="columns/rows/bits",
                        )
                    ),
                    vol.Optional(CONF_STEP_INTERVAL_MS): NumberSelector(
                        NumberSelectorConfig(
                            min=1, max=3000, step=1, unit_of_measurement="milliseconds"
                        )
                    ),
                }
            )
        ),
    }
)
BOARD_OPTIONS_SCHEMA = OPTIONS_SCHEMA.extend(
    {vol.Optional(CONF_SHOW_FRAME, default=True): bool}
)
# Newer Flagships have a heart in place of the degree sign, as Notes always do
FLAGSHIP_OPTIONS_SCHEMA = BOARD_OPTIONS_SCHEMA.extend(
    {vol.Optional(CONF_HEART, default=False): bool}
)


async def _board_options_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Return the board options, with the heart option for Flagships only."""
    entry = handler.parent_handler.config_entry
    # Virtual boards store their model; physical boards report it once loaded
    model = entry.data.get(CONF_BOARD_MODEL)
    coordinator = getattr(entry, "runtime_data", None)
    if model is None and coordinator is not None and coordinator.model is not None:
        model = coordinator.model.model
    # Only Flagships are asked about the heart during setup
    if model == MODEL_FLAGSHIP or CONF_HEART in entry.options:
        return FLAGSHIP_OPTIONS_SCHEMA
    return BOARD_OPTIONS_SCHEMA


OPTIONS_FLOW = {"init": SchemaFlowFormStep(_board_options_schema)}
# Arrays have no color of their own; each board in the array uses its own color
ARRAY_OPTIONS_SCHEMA = vol.Schema(
    {key: value for key, value in OPTIONS_SCHEMA.schema.items() if key != CONF_MODEL}
).extend({vol.Optional(CONF_SHOW_FRAME, default=False): bool})
ARRAY_OPTIONS_FLOW = {"init": SchemaFlowFormStep(ARRAY_OPTIONS_SCHEMA)}

VESTABOARD_CONNECTED_MESSAGE = [
    "{63}{63}{63}{63}{63}{63}{64}{64}{64}{64}{64}{64}{64}{64}{64}{65}{65}{65}{65}{65}{65}{65}",
    "{63}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{65}",
    "{63}{0} Now connected to {0}{65}",
    "{68}{0}{0} Home Assistant {0}{0}{66}",
    "{68}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{0}{66}",
    "{68}{68}{68}{68}{68}{68}{68}{67}{67}{67}{67}{67}{67}{67}{67}{67}{66}{66}{66}{66}{66}{66}",
]
VESTABOARD_NOTE_CONNECTED_MESSAGE = [
    "{63}Now connected{68}",
    "{63}{64}{0} to Home {0}{67}{68}",
    "{63}{64}{65}Assistant{66}{67}{68}",
]


# How long Notes show their name while arranging, if the flow is never closed
IDENTIFY_DURATION = timedelta(minutes=10)


def _arrangements(count: int) -> dict[str, tuple[int, int]]:
    """Return every grid arrangement that fits within count boards.

    Keys are "<rows>x<columns>", ordered by number of boards, then wide before tall.
    """
    sizes = [
        (rows, columns)
        for rows in range(1, count + 1)
        for columns in range(1, count + 1)
        if 2 <= rows * columns <= count
    ]
    sizes.sort(key=lambda size: (size[0] * size[1], size[0]))
    return {f"{rows}x{columns}": (rows, columns) for rows, columns in sizes}


def _arrangement_label(rows: int, columns: int) -> str:
    """Return a readable label for a grid arrangement."""
    if rows == 1:
        return f"{columns} Notes side by side"
    if columns == 1:
        return f"{rows} Notes stacked"
    return f"{rows * columns} Notes in {rows} rows of {columns}"


@callback
def _async_get_array_candidates(hass: HomeAssistant) -> list[str]:
    """Return entry ids of loaded Vestaboards that can be part of an array.

    Only Vestaboard Notes are supported in arrays for now.
    """
    return [
        entry.entry_id
        for entry in hass.config_entries.async_entries(DOMAIN)
        if not is_array_entry(entry)
        and entry.state is ConfigEntryState.LOADED
        and entry.runtime_data.model is not None
        and entry.runtime_data.model.model == MODEL_NOTE
    ]


def _array_unique_id(layout: list[list[str]]) -> str:
    """Return the unique id for an array with this layout."""
    return f"{ENTRY_TYPE_ARRAY}:{'|'.join(','.join(row) for row in layout)}"


@callback
def _async_board_label(hass: HomeAssistant, entry_id: str) -> str:
    """Return a board's name, made distinct if another Note has the same name.

    Boards set up without a custom name are all titled "Vestaboard", so a
    board sharing its name is labeled with its host, or as virtual.
    """
    if (entry := hass.config_entries.async_get_entry(entry_id)) is None:
        return entry_id
    titles = [
        candidate.title
        for candidate_id in _async_get_array_candidates(hass)
        if (candidate := hass.config_entries.async_get_entry(candidate_id))
    ]
    if titles.count(entry.title) < 2:
        return entry.title
    if get_entry_type(entry) == ENTRY_TYPE_VIRTUAL:
        return f"{entry.title} (virtual {entry.entry_id[-4:]})"
    return f"{entry.title} ({entry.data[CONF_HOST]})"


@callback
def _async_board_selector(hass: HomeAssistant, entry_ids: list[str]) -> SelectSelector:
    """Return a selector for choosing one of these boards."""
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(
                    value=entry_id, label=_async_board_label(hass, entry_id)
                )
                for entry_id in entry_ids
            ]
        )
    )


def _markdown_escape(text: str) -> str:
    """Escape characters that would break markdown tables or formatting."""
    for char in "\\|*_[]":
        text = text.replace(char, f"\\{char}")
    return text


def _layout_markdown(cells: list[list[str]]) -> str:
    """Return a markdown table of an array's positions, one cell per board."""
    columns = len(cells[0])
    header = [f"Column {column + 1}" for column in range(columns)]
    lines = [header, ["---"] * columns, *cells]
    return "\n".join(f"| {' | '.join(line)} |" for line in lines)


@callback
def _async_boards_markdown(hass: HomeAssistant, entry_ids: list[str]) -> str:
    """Return each board's name with an image of what it's showing."""
    entity_registry = er.async_get(hass)
    parts = []
    for entry_id in entry_ids:
        part = f"**{_markdown_escape(_async_board_label(hass, entry_id))}**"
        if (
            (
                entity_id := entity_registry.async_get_entity_id(
                    Platform.IMAGE, DOMAIN, f"{entry_id}-board"
                )
            )
            and (state := hass.states.get(entity_id))
            and (picture := state.attributes.get(ATTR_ENTITY_PICTURE))
        ):
            part += f"\n![]({picture})"
        parts.append(part)
    return "\n\n".join(parts)


class VestaboardConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Vestaboard."""

    VERSION = 1

    host: str | None = None
    api_key: str | None = None
    name: str | None = None

    # Board setup state, kept until the appearance step creates the entry
    board_model: str | None = None
    entry_data: dict[str, Any] | None = None

    # Array setup state
    array_rows: int = 0
    array_columns: int = 0
    array_boards: list[str]
    # Notes showing their name, each with the temporary message it was showing
    # before (characters and expiration), if any
    identified_boards: dict[str, tuple[list[list[int]], datetime] | None] | None = None
    identify_expiration: datetime | None = None

    @callback
    def async_remove(self) -> None:
        """Restore any Notes showing their name once the flow ends, however it ends.

        A Note goes back to the temporary message it was showing before, if that
        hasn't expired, or else to its persistent message. A Note whose name
        already expired restored itself; one that was sent a newer temporary
        message during the flow is left alone.
        """
        for entry_id, previous in (self.identified_boards or {}).items():
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if entry is None or entry.state is not ConfigEntryState.LOADED:
                continue
            coordinator = entry.runtime_data
            if coordinator.temporary_message_expiration != self.identify_expiration:
                continue
            if previous and previous[1] > dt_util.now():
                characters, expiration = previous
                restore = coordinator.async_write_message(
                    {"characters": characters}, expiration
                )
            else:
                restore = coordinator.async_clear_temporary_message()
            self.hass.async_create_task(restore, f"vestaboard restore {entry.title}")

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> SchemaOptionsFlowHandler:
        """Get the options flow for this handler."""
        if is_array_entry(config_entry):
            return SchemaOptionsFlowHandler(config_entry, ARRAY_OPTIONS_FLOW)
        return SchemaOptionsFlowHandler(config_entry, OPTIONS_FLOW)

    async def async_step_dhcp(self, discovery_info: dhcp.DhcpServiceInfo) -> FlowResult:
        """Handle dhcp discovery."""
        self.host = discovery_info.ip
        self.name = discovery_info.hostname
        await self.async_set_unique_id(discovery_info.macaddress)
        self._abort_if_unique_id_configured(updates={CONF_HOST: self.host})

        # The board may have reconnected on a different network interface (e.g.
        # switching between 2.4 GHz and 5 GHz), giving it a different MAC and
        # therefore a different unique_id than the one stored on the config entry.
        # Try each existing entry's API key against the new IP; if it responds,
        # this is the same board and we can silently update the stored host.
        for entry in self._async_device_entries():
            try:
                client = await create_client(
                    self.hass,
                    {CONF_HOST: self.host, CONF_API_KEY: entry.data[CONF_API_KEY]},
                )
                if await client.check_endpoint() == EndpointStatus.VALID:
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={CONF_HOST: self.host},
                        reason="already_configured",
                        unique_id=self.unique_id,
                        reload_even_if_entry_is_unchanged=False,
                    )
            except asyncio.CancelledError:
                raise
            except (
                ClientConnectorError,
                asyncio.TimeoutError,
                OSError,
                ValueError,
            ) as ex:
                _LOGGER.debug(
                    "Failed to probe entry %s at %s during DHCP discovery: %s",
                    entry.entry_id,
                    self.host,
                    ex,
                )

        return await self.async_step_api_key()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        menu_options = ["device", "virtual"]
        if len(_async_get_array_candidates(self.hass)) >= 2:
            menu_options.append("array")
        return self.async_show_menu(step_id="user", menu_options=menu_options)

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle setting up a single Vestaboard."""
        return await self._async_step("device", STEP_USER_DATA_SCHEMA, user_input)

    async def async_step_virtual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle setting up a virtual Vestaboard, which has no hardware behind it."""
        if user_input is not None:
            self.name = user_input[CONF_NAME]
            self.board_model = user_input[CONF_BOARD_MODEL]
            self.entry_data = {
                CONF_ENTRY_TYPE: ENTRY_TYPE_VIRTUAL,
                CONF_BOARD_MODEL: self.board_model,
            }
            return await self.async_step_appearance()

        return self.async_show_form(step_id="virtual", data_schema=STEP_VIRTUAL_SCHEMA)

    async def async_step_appearance(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose the board's color, and for Flagships whether it has the heart.

        These are saved as options, so they can be changed later.
        """
        if user_input is not None:
            return self.async_create_entry(
                title=self.name or "Vestaboard",
                data=self.entry_data,
                options=user_input,
            )

        schema = vol.Schema(
            {vol.Required(CONF_MODEL, default=COLOR_BLACK): COLOR_SCHEMA}
        )
        if self.board_model == MODEL_FLAGSHIP:
            schema = schema.extend({vol.Required(CONF_HEART, default=False): bool})
        return self.async_show_form(
            step_id="appearance",
            data_schema=schema,
            description_placeholders={
                "model": f"Vestaboard {(self.board_model or '').capitalize()}".strip()
            },
        )

    async def async_step_array(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle setting up, or reconfiguring, an array of existing Vestaboards."""
        arrangements = _arrangements(len(_async_get_array_candidates(self.hass)))
        if not arrangements:
            return self.async_abort(reason="not_enough_boards")

        name = "Vestaboard Note array"
        arrangement = next(iter(arrangements))
        if current_layout := self._current_array_layout():
            name = self._get_reconfigure_entry().title
            current = f"{len(current_layout)}x{len(current_layout[0])}"
            arrangement = current if current in arrangements else arrangement

        if user_input is not None:
            rows, columns = arrangements[user_input[CONF_ARRANGEMENT]]
            self.name = user_input[CONF_NAME]
            self.array_rows = rows
            self.array_columns = columns
            self.array_boards = []
            if user_input[CONF_IDENTIFY]:
                await self._async_identify_boards()
            return await self.async_step_array_board()

        return self.async_show_form(
            step_id="array",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=name): str,
                    vol.Required(CONF_ARRANGEMENT, default=arrangement): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(
                                    value=key, label=_arrangement_label(*size)
                                )
                                for key, size in arrangements.items()
                            ]
                        )
                    ),
                    vol.Required(CONF_IDENTIFY, default=True): bool,
                }
            ),
            description_placeholders={
                "action": "Reconfigure" if current_layout else "Create"
            },
        )

    async def async_step_array_board(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select the Vestaboard for each position in the array, one at a time."""
        candidates = _async_get_array_candidates(self.hass)

        if user_input is not None:
            if user_input[CONF_BOARD] not in candidates:
                return self.async_abort(reason="board_unavailable")
            self.array_boards.append(user_input[CONF_BOARD])

        if len(self.array_boards) == self.array_rows * self.array_columns:
            layout = [
                self.array_boards[
                    row * self.array_columns : (row + 1) * self.array_columns
                ]
                for row in range(self.array_rows)
            ]
            unique_id = _array_unique_id(layout)
            if self.source == SOURCE_RECONFIGURE:
                entry = self._get_reconfigure_entry()
                if any(
                    other.unique_id == unique_id and other.entry_id != entry.entry_id
                    for other in self._async_current_entries()
                ):
                    return self.async_abort(reason="already_configured")
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=unique_id,
                    title=self.name,
                    data_updates={CONF_LAYOUT: layout},
                )
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=self.name,
                data={CONF_ENTRY_TYPE: ENTRY_TYPE_ARRAY, CONF_LAYOUT: layout},
            )

        candidates = [
            entry_id for entry_id in candidates if entry_id not in self.array_boards
        ]
        if not candidates:
            return self.async_abort(reason="not_enough_boards")

        position = len(self.array_boards)
        row, column = divmod(position, self.array_columns)
        current = None
        if (current_layout := self._current_array_layout()) and (
            row < len(current_layout) and column < len(current_layout[row])
        ):
            current = current_layout[row][column]
        return self.async_show_form(
            step_id="array_board",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_BOARD,
                        default=current if current in candidates else vol.UNDEFINED,
                    ): _async_board_selector(self.hass, candidates)
                }
            ),
            description_placeholders={
                "layout": self._array_layout_markdown(),
                "boards": _async_boards_markdown(self.hass, candidates),
            },
            last_step=position + 1 == self.array_rows * self.array_columns,
        )

    def _current_array_layout(self) -> list[list[str]] | None:
        """Return the layout of the array being reconfigured, if any."""
        if self.source != SOURCE_RECONFIGURE:
            return None
        return self._get_reconfigure_entry().data[CONF_LAYOUT]

    def _array_layout_markdown(self) -> str:
        """Return a table of the array so far, marking the position being chosen."""
        position = len(self.array_boards)
        cells = []
        for index in range(self.array_rows * self.array_columns):
            if index < position:
                label = _async_board_label(self.hass, self.array_boards[index])
                cells.append(_markdown_escape(label))
            elif index == position:
                cells.append("**➜ choose below**")
            else:
                cells.append("·")
        return _layout_markdown(
            [
                cells[row * self.array_columns : (row + 1) * self.array_columns]
                for row in range(self.array_rows)
            ]
        )

    async def _async_identify_boards(self) -> None:
        """Show each available Note's name on it as a temporary message.

        The messages are cleared when the flow ends, and expire on their own in
        case the flow is abandoned without being closed.
        """
        expiration = dt_util.now() + IDENTIFY_DURATION
        self.identify_expiration = expiration
        self.identified_boards = {}
        for entry_id in _async_get_array_candidates(self.hass):
            entry = self.hass.config_entries.async_get_entry(entry_id)
            coordinator = entry.runtime_data
            previous = None
            current = coordinator.temporary_message_expiration
            if current and current > dt_util.now() and coordinator.data:
                previous = ([list(row) for row in coordinator.data], current)
            try:
                characters = coordinator.model.parse_template(
                    _async_board_label(self.hass, entry_id).upper(),
                    {CONF_JUSTIFY: ALIGN_CENTER, CONF_ALIGN: ALIGN_CENTER},
                )
                # If the name expires before the flow ends, the Note goes back
                # to its earlier temporary message by itself
                await coordinator.async_write_message(
                    {"characters": characters}, expiration, restore_after=previous
                )
            except Exception:  # pylint: disable=broad-except
                # A Note that can't show its name is still offered, just unlabeled
                _LOGGER.warning(
                    "Unable to show its name on %s", entry.title, exc_info=True
                )
                continue
            self.identified_boards[entry_id] = previous

    async def async_step_api_key(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle step to setup API key."""
        return await self._async_step("api_key", STEP_API_KEY_SCHEMA, user_input)

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Perform reauth upon an API key error."""
        self.host = user_input[CONF_HOST]
        self.api_key = user_input[CONF_API_KEY]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Perform reauth upon an API key error."""
        return await self._async_step("reauth_confirm", STEP_API_KEY_SCHEMA, user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reconfiguration to update the host."""
        reconfigure_entry = self._get_reconfigure_entry()
        if (entry_type := get_entry_type(reconfigure_entry)) == ENTRY_TYPE_ARRAY:
            return await self.async_step_array()
        if entry_type != ENTRY_TYPE_DEVICE:
            return self.async_abort(reason=f"{entry_type}_reconfigure_unsupported")
        errors = {}

        if user_input is not None:
            self.host = user_input[CONF_HOST]
            if self.host == reconfigure_entry.data[CONF_HOST]:
                return self.async_abort(reason="already_configured")

            self.api_key = reconfigure_entry.data[CONF_API_KEY]
            if not (
                errors := await self.validate_client(
                    {CONF_API_KEY: self.api_key}, write_connected_message=False
                )
            ):
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data_updates={CONF_HOST: self.host},
                    reason="reconfigure_successful",
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_HOST): str}),
                {CONF_HOST: reconfigure_entry.data[CONF_HOST]},
            ),
            errors=errors,
        )

    async def _async_step(
        self, step_id: str, schema: vol.Schema, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle step setup."""
        if step_id != "reauth_confirm" and (
            abort := await self._abort_if_configured(user_input)
        ):
            return abort

        errors = {}

        if user_input is not None and not (
            errors := await self.validate_client(user_input)
        ):
            data = {
                CONF_HOST: user_input.get(CONF_HOST, self.host),
                CONF_API_KEY: self.api_key,
            }
            if existing_entry := self.hass.config_entries.async_get_entry(
                self.context.get("entry_id")
            ):
                self.hass.config_entries.async_update_entry(existing_entry, data=data)
                await self.hass.config_entries.async_reload(existing_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

            self.entry_data = data
            return await self.async_step_appearance()

        schema = self.add_suggested_values_to_schema(
            schema, {CONF_API_KEY: self.api_key}
        )
        return self.async_show_form(step_id=step_id, data_schema=schema, errors=errors)

    async def validate_client(
        self, user_input: dict[str, Any], write_connected_message: bool = True
    ) -> dict[str, str]:
        """Validate client setup."""
        errors = {}
        try:
            client = await create_client(self.hass, {"host": self.host} | user_input)
            if (status := await client.check_endpoint()) == EndpointStatus.UNKNOWN:
                errors["base"] = "invalid_host"
            elif status == EndpointStatus.INVALID_API_KEY:
                errors["base"] = "invalid_api_key"
            elif status == EndpointStatus.VALID:
                if write_connected_message:
                    model = VestaboardModel.from_color(COLOR_BLACK, client.data)
                    self.board_model = model.model
                    message = (
                        VESTABOARD_CONNECTED_MESSAGE
                        if model.is_flagship
                        else VESTABOARD_NOTE_CONNECTED_MESSAGE
                    )
                    json = {"characters": model.parse_template("\n".join(message))}
                    await client.write_message(json)
                self.api_key = client.api_key
            else:
                errors["base"] = "unknown"
        except asyncio.TimeoutError:
            errors["base"] = "timeout_connect"
        except ClientConnectorError:
            errors["base"] = "invalid_host"
        except Exception as ex:  # noqa: BLE001  # pylint: disable=broad-except
            _LOGGER.error(ex)
            errors["base"] = "unknown"
        return errors

    async def _abort_if_configured(
        self, user_input: dict[str, Any] | None
    ) -> FlowResult | None:
        """Abort if configured."""
        if self.host or user_input:
            data = {CONF_HOST: self.host, **(user_input or {})}
            for entry in self._async_device_entries():
                if entry.data[CONF_HOST] == data[CONF_HOST] or entry.data[
                    CONF_API_KEY
                ] == data.get(CONF_API_KEY):
                    if CONF_API_KEY not in data:
                        data[CONF_API_KEY] = entry.data[CONF_API_KEY]
                    if not await self.validate_client(
                        data, write_connected_message=False
                    ):
                        return self.async_update_reload_and_abort(
                            entry,
                            unique_id=self.unique_id or entry.unique_id,
                            data_updates={
                                CONF_HOST: data.get(CONF_HOST, self.host),
                                CONF_API_KEY: self.api_key,
                            },
                            reason="already_configured",
                        )
        return None

    @callback
    def _async_device_entries(self) -> list[ConfigEntry]:
        """Return config entries for physical Vestaboards."""
        return [
            entry
            for entry in self._async_current_entries()
            if get_entry_type(entry) == ENTRY_TYPE_DEVICE
        ]
