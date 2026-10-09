"""Config flow for Vestaboard integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import ClientConnectorError
import voluptuous as vol

from homeassistant.components import dhcp
from homeassistant.config_entries import ConfigEntry, ConfigFlow
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult, section
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaFlowFormStep,
    SchemaOptionsFlowHandler,
)
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    TimeSelector,
)

from .client import EndpointStatus
from .const import (
    COLOR_BLACK,
    COLOR_WHITE,
    CONF_BOARD_MODEL,
    CONF_ENABLEMENT_TOKEN,
    CONF_ENTRY_TYPE,
    CONF_MODEL,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_SHOW_FRAME,
    CONF_STEP_INTERVAL_MS,
    CONF_STEP_SIZE,
    CONF_STRATEGY,
    CONF_TRANSITIONS,
    DOMAIN,
    ENTRY_TYPE_DEVICE,
    ENTRY_TYPE_VIRTUAL,
)
from .helpers import create_client, get_entry_type
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
OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MODEL, default=COLOR_BLACK): vol.In(
            {COLOR_BLACK: "Black", COLOR_WHITE: "White"}
        ),
        vol.Optional(CONF_QUIET_START): TimeSelector(),
        vol.Optional(CONF_QUIET_END): TimeSelector(),
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
OPTIONS_FLOW = {"init": SchemaFlowFormStep(BOARD_OPTIONS_SCHEMA)}

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


class VestaboardConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Vestaboard."""

    VERSION = 1

    host: str | None = None
    api_key: str | None = None
    name: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> SchemaOptionsFlowHandler:
        """Get the options flow for this handler."""
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
        return self.async_show_menu(step_id="user", menu_options=["device", "virtual"])

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
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={
                    CONF_ENTRY_TYPE: ENTRY_TYPE_VIRTUAL,
                    CONF_BOARD_MODEL: user_input[CONF_BOARD_MODEL],
                },
            )

        return self.async_show_form(step_id="virtual", data_schema=STEP_VIRTUAL_SCHEMA)

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
        if (entry_type := get_entry_type(reconfigure_entry)) != ENTRY_TYPE_DEVICE:
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

        if user_input is not None:
            if not (errors := await self.validate_client(user_input)):
                data = {
                    CONF_HOST: user_input.get(CONF_HOST, self.host),
                    CONF_API_KEY: self.api_key,
                }
                if existing_entry := self.hass.config_entries.async_get_entry(
                    self.context.get("entry_id")
                ):
                    self.hass.config_entries.async_update_entry(
                        existing_entry, data=data
                    )
                    await self.hass.config_entries.async_reload(existing_entry.entry_id)
                    return self.async_abort(reason="reauth_successful")

                return self.async_create_entry(
                    title=self.name or "Vestaboard",
                    data=data,
                )

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
        except Exception as ex:  # pylint: disable=broad-except
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
