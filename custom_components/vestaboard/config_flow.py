"""Config flow for Vestaboard integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import ClientConnectorError
from httpx import ConnectError, HTTPStatusError
import voluptuous as vol

from homeassistant.components import dhcp
from homeassistant.config_entries import ConfigEntry, ConfigFlow
from homeassistant.const import CONF_API_KEY, CONF_HOST
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaFlowFormStep,
    SchemaOptionsFlowHandler,
)
from homeassistant.helpers.selector import TimeSelector

from .const import (
    COLOR_BLACK,
    COLOR_WHITE,
    CONF_ENABLEMENT_TOKEN,
    CONF_MODEL,
    CONF_QUIET_END,
    CONF_QUIET_START,
    DOMAIN,
)
from .helpers import construct_message, create_client
from .vestaboard_model import VestaboardModel

_LOGGER = logging.getLogger(__name__)

STEP_API_KEY_SCHEMA = vol.Schema(
    {vol.Required(CONF_API_KEY): str, vol.Optional(CONF_ENABLEMENT_TOKEN): bool}
)
STEP_USER_DATA_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str}).extend(
    STEP_API_KEY_SCHEMA.schema
)
OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MODEL, default=COLOR_BLACK): vol.In(
            {COLOR_BLACK: "Black", COLOR_WHITE: "White"}
        ),
        vol.Optional(CONF_QUIET_START): TimeSelector(),
        vol.Optional(CONF_QUIET_END): TimeSelector(),
    }
)
OPTIONS_FLOW = {"init": SchemaFlowFormStep(OPTIONS_SCHEMA)}

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
    def async_get_options_flow(config_entry: ConfigEntry) -> SchemaOptionsFlowHandler:
        """Get the options flow for this handler."""
        return SchemaOptionsFlowHandler(config_entry, OPTIONS_FLOW)

    async def async_step_dhcp(self, discovery_info: dhcp.DhcpServiceInfo) -> FlowResult:
        """Handle dhcp discovery."""
        self.host = discovery_info.ip
        self.name = discovery_info.hostname
        await self.async_set_unique_id(discovery_info.macaddress)
        self._abort_if_unique_id_configured(updates={CONF_HOST: self.host})
        return await self.async_step_api_key()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        return await self._async_step("user", STEP_USER_DATA_SCHEMA, user_input)

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
        self, user_input: dict[str, Any], write: bool = True
    ) -> dict[str, str]:
        """Validate client setup."""
        errors = {}
        try:
            client = await self.hass.async_add_executor_job(
                create_client, {"host": self.host} | user_input
            )
            if not (data := client.read_message()):
                errors["base"] = "invalid_api_key"
            else:
                if write:
                    model = VestaboardModel.from_color(COLOR_BLACK, data)
                    message = (
                        VESTABOARD_CONNECTED_MESSAGE
                        if model.is_flagship
                        else VESTABOARD_NOTE_CONNECTED_MESSAGE
                    )
                    client.write_message(construct_message("\n".join(message)))
                self.api_key = client.api_key
        except asyncio.TimeoutError:
            errors["base"] = "timeout_connect"
        except ConnectError:
            errors["base"] = "invalid_host"
        except ClientConnectorError:
            errors["base"] = "unknown"
        except HTTPStatusError as err:
            errors["base"] = str(err)
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
            for entry in self._async_current_entries():
                if entry.data[CONF_HOST] == data[CONF_HOST] or entry.data[
                    CONF_API_KEY
                ] == data.get(CONF_API_KEY):
                    if not await self.validate_client(user_input, write=False):
                        return self.async_update_reload_and_abort(
                            entry,
                            unique_id=self.unique_id or entry.unique_id,
                            data_updates={
                                CONF_HOST: user_input.get(CONF_HOST, self.host),
                                CONF_API_KEY: self.api_key,
                            },
                            reason="already_configured",
                        )
        return None
