"""Config flow for Vestaboard integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import ClientConnectorError
import voluptuous as vol

from homeassistant.components import dhcp
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_API_KEY, CONF_HOST
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult, section
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaFlowFormStep,
)
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    TimeSelector,
)

from .client import EndpointStatus
from .const import (
    COLOR_BLACK,
    COLOR_WHITE,
    CONF_ENABLEMENT_TOKEN,
    CONF_MODEL,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_STEP_INTERVAL_MS,
    CONF_STEP_SIZE,
    CONF_STRATEGY,
    CONF_TRANSITIONS,
    DOMAIN,
)
from .helpers import create_client
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
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> VestaboardOptionsFlowHandler:
        """Get the options flow for this handler."""
        return VestaboardOptionsFlowHandler()

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
        for entry in self._async_current_entries():
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
                    )
            except Exception:  # pylint: disable=broad-except
                pass

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
            client = await create_client(self.hass, {"host": self.host} | user_input)
            if (status := await client.check_endpoint()) == EndpointStatus.UNKNOWN:
                errors["base"] = "invalid_host"
            elif status == EndpointStatus.INVALID_API_KEY:
                errors["base"] = "invalid_api_key"
            elif status == EndpointStatus.VALID:
                if write:
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
            for entry in self._async_current_entries():
                if entry.data[CONF_HOST] == data[CONF_HOST] or entry.data[
                    CONF_API_KEY
                ] == data.get(CONF_API_KEY):
                    if CONF_API_KEY not in data:
                        data[CONF_API_KEY] = entry.data[CONF_API_KEY]
                    if not await self.validate_client(data, write=False):
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


class VestaboardOptionsFlowHandler(OptionsFlow):
    """Handle options flow for Vestaboard."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        current_host = self.config_entry.data[CONF_HOST]

        if user_input is not None:
            new_host = user_input.get(CONF_HOST, current_host)
            if new_host != current_host:
                try:
                    client = await create_client(
                        self.hass,
                        {
                            CONF_HOST: new_host,
                            CONF_API_KEY: self.config_entry.data[CONF_API_KEY],
                        },
                    )
                    if await client.check_endpoint() == EndpointStatus.UNKNOWN:
                        errors[CONF_HOST] = "invalid_host"
                except asyncio.TimeoutError:
                    errors[CONF_HOST] = "timeout_connect"
                except ClientConnectorError:
                    errors[CONF_HOST] = "invalid_host"
                except Exception as ex:  # pylint: disable=broad-except
                    _LOGGER.error(ex)
                    errors["base"] = "unknown"

            if not errors:
                if new_host != current_host:
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data={**self.config_entry.data, CONF_HOST: new_host},
                    )
                return self.async_create_entry(
                    data={k: v for k, v in user_input.items() if k != CONF_HOST}
                )

        combined_schema = vol.Schema({vol.Required(CONF_HOST): str}).extend(
            OPTIONS_SCHEMA.schema
        )
        suggested = (
            user_input
            if user_input is not None
            else {CONF_HOST: current_host, **self.config_entry.options}
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(combined_schema, suggested),
            errors=errors,
        )
