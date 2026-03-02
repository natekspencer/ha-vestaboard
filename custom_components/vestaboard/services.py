"""Support for Vestaboard services."""

from __future__ import annotations

from datetime import timedelta

import voluptuous as vol

from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant, HomeAssistantError, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util.dt import now as dt_now

from .const import (
    ALIGN_CENTER,
    ALIGN_HORIZONTAL,
    ALIGN_VERTICAL,
    CONF_ALIGN,
    CONF_BYPASS_QUIET_HOURS,
    CONF_DURATION,
    CONF_JUSTIFY,
    CONF_MESSAGE,
    CONF_STEP_INTERVAL_MS,
    CONF_STEP_SIZE,
    CONF_STRATEGY,
    CONF_TRANSITIONS,
    CONF_VBML,
    DOMAIN,
    SERVICE_MESSAGE,
)
from .helpers import async_get_coordinator_by_device_id

_calendar = vol.Schema(
    {
        vol.Required("month"): vol.All(vol.Coerce(int), vol.Range(min=1, max=12)),
        vol.Required("year"): vol.Coerce(int),
        vol.Optional("defaultDayColor"): vol.All(
            vol.Coerce(int), vol.Range(min=63, max=70)
        ),
        vol.Optional("days"): vol.Coerce(dict[str, int]),
        vol.Optional("hideSMTWTFS"): vol.Coerce(bool),
        vol.Optional("hideDates"): vol.Coerce(bool),
        vol.Optional("hideMonthYear"): vol.Coerce(bool),
    }
)
_character_codes = vol.All(vol.Coerce(int), vol.Range(min=0, max=71))
_random_colors = vol.Schema(
    {vol.Optional("colors"): [vol.All(int, vol.Range(min=63, max=71))]}
)
_raw_characters = vol.All(cv.ensure_list, [vol.All(cv.ensure_list, [_character_codes])])
_style = vol.Schema(
    {
        vol.Optional("height"): vol.All(vol.Coerce(int), vol.Range(min=1, max=6)),
        vol.Optional("width"): vol.All(vol.Coerce(int), vol.Range(min=1, max=22)),
        vol.Optional(CONF_JUSTIFY): vol.In(ALIGN_HORIZONTAL),
        vol.Optional(CONF_ALIGN): vol.In(ALIGN_VERTICAL),
        vol.Optional("absolutePosition"): vol.Schema(
            {
                vol.Required("x"): vol.All(vol.Coerce(int), vol.Range(min=0, max=21)),
                vol.Required("y"): vol.All(vol.Coerce(int), vol.Range(min=0, max=5)),
            }
        ),
    }
)
_component = vol.All(
    vol.Schema(
        {
            vol.Optional("template"): cv.string,
            vol.Optional("rawCharacters"): _raw_characters,
            vol.Optional("calendar"): _calendar,
            vol.Optional("randomColors"): _random_colors,
            vol.Optional("style"): _style,
        }
    ),
    cv.has_at_least_one_key("template", "rawCharacters", "calendar", "randomColors"),
)

VBML_SCHEMA = vol.Schema(
    {
        vol.Optional("props"): {cv.string: cv.string},
        # Styles to set the size of the rendered array of arrays is purposefully missing and controlled by code
        vol.Required("components"): vol.All(cv.ensure_list, [_component]),
    }
)

SERVICE_MESSAGE_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required(CONF_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional(CONF_MESSAGE): cv.string,
            vol.Optional(CONF_JUSTIFY, default=ALIGN_CENTER): vol.In(ALIGN_HORIZONTAL),
            vol.Optional(CONF_ALIGN, default=ALIGN_CENTER): vol.In(ALIGN_VERTICAL),
            vol.Optional(CONF_VBML): VBML_SCHEMA,
            vol.Optional(CONF_STRATEGY): vol.In(CONF_TRANSITIONS),
            vol.Optional(CONF_STEP_INTERVAL_MS): cv.positive_int,
            vol.Optional(CONF_STEP_SIZE): cv.positive_int,
            vol.Optional(CONF_DURATION): vol.All(
                vol.Coerce(int), vol.Range(min=10, max=43200)
            ),
            vol.Optional(CONF_BYPASS_QUIET_HOURS): cv.boolean,
        },
    ),
    cv.has_at_least_one_key(CONF_MESSAGE, CONF_VBML),
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for the Vestaboard integration."""

    async def _async_service_message(call: ServiceCall) -> None:
        """Send a message to a Vestaboard."""
        if not (vbml := call.data.get(CONF_VBML)):
            align = call.data.get(CONF_ALIGN, ALIGN_CENTER)
            justify = call.data.get(CONF_JUSTIFY, ALIGN_CENTER)
            message = {
                "style": {CONF_ALIGN: align, CONF_JUSTIFY: justify},
                "template": call.data.get(CONF_MESSAGE, "")
                .replace("  ", "{70}{70}")
                .replace("\n\n", "\n{70}\n"),
            }
            components = [message]

            vbml = {"components": components}

        json = {}
        if strategy := call.data.get(CONF_STRATEGY):
            json[CONF_STRATEGY] = strategy
            if step_interval := call.data.get(CONF_STEP_INTERVAL_MS):
                json[CONF_STEP_INTERVAL_MS] = step_interval
            if step_size := call.data.get(CONF_STEP_SIZE):
                json[CONF_STEP_SIZE] = step_size

        for device_id in call.data[CONF_DEVICE_ID]:
            coordinator = async_get_coordinator_by_device_id(hass, device_id)
            if not call.data.get(CONF_BYPASS_QUIET_HOURS) and coordinator.quiet_hours():
                continue

            if coordinator.model is None:
                await coordinator.async_request_refresh()
            if coordinator.model is None:
                raise HomeAssistantError("Vestaboard model is not initialized")
            try:
                rows = coordinator.model.parse_vbml(vbml)
            except Exception as ex:
                raise HomeAssistantError(f"Invalid VBML payload: {ex}") from ex
            json["characters"] = rows

            if duration := call.data.get(CONF_DURATION):  # This is a temporary message
                if coordinator._cancel_cb:
                    coordinator._cancel_cb()
                expiration = dt_now() + timedelta(seconds=duration)
                coordinator.temporary_message_expiration = expiration
                await coordinator.write_and_update_state(json)
                coordinator._cancel_cb = async_track_point_in_time(
                    hass, coordinator._handle_temporary_message_expiration, expiration
                )
            else:
                coordinator.persistent_message = rows
                expiration = coordinator.temporary_message_expiration
                if not (expiration and expiration > dt_now()):
                    await coordinator.write_and_update_state(json)

    hass.services.async_register(
        DOMAIN,
        SERVICE_MESSAGE,
        _async_service_message,
        schema=SERVICE_MESSAGE_SCHEMA,
    )
