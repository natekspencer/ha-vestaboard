"""Websocket commands for the Vestaboard composer panel."""

from __future__ import annotations

import base64
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import (
    ALIGN_CENTER,
    ALIGN_HORIZONTAL,
    ALIGN_VERTICAL,
    COLOR_BLACK,
    CONF_ALIGN,
    CONF_JUSTIFY,
    CONF_MESSAGE,
    CONF_SHOW_FRAME,
    DOMAIN,
)
from .coordinator import VestaboardConfigEntry
from .helpers import (
    PRINTABLE,
    async_get_coordinator_by_device_id,
    emoji_png,
    get_entry_type,
    logo_layout,
)
from .services import message_vbml
from .vestaboard_model import (
    BIT_HEIGHT,
    BIT_HEIGHT_SPACING,
    BIT_WIDTH,
    BIT_WIDTH_SPACING,
    COLOR_SCHEMES,
    HEART_CODE,
    HEART_EMOJI,
    VestaboardArrayModel,
    VestaboardModel,
)


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    """Register the composer's websocket commands."""
    websocket_api.async_register_command(hass, websocket_boards)
    websocket_api.async_register_command(hass, websocket_layout)


DATA_COMPOSER_ASSETS = "composer_assets"


def _render_assets() -> tuple[str, dict[str, dict[str, float]]]:
    """Render the heart and measure each model's logo, as the board image does."""
    logos = {
        model: logo_layout(VestaboardModel(COLOR_BLACK, model))
        for model in VestaboardModel.all_models()
    }
    heart = base64.b64encode(emoji_png(HEART_EMOJI)).decode()
    return f"data:image/png;base64,{heart}", logos


async def _async_get_assets(
    hass: HomeAssistant,
) -> tuple[str, dict[str, dict[str, float]]]:
    """Return the heart image and logo layouts, rendering them the first time."""
    if (assets := hass.data[DOMAIN].get(DATA_COMPOSER_ASSETS)) is None:
        # Loading fonts reads files, so do it outside the event loop
        assets = await hass.async_add_executor_job(_render_assets)
        hass.data[DOMAIN][DATA_COMPOSER_ASSETS] = assets
    return assets


def _board_info(
    entry: VestaboardConfigEntry, device_id: str, logos: dict[str, dict[str, float]]
) -> dict[str, Any] | None:
    """Return what the composer needs to draw and send to a board or array."""
    coordinator = entry.runtime_data
    model = coordinator.model
    if model is None or coordinator.data is None:
        return None

    if isinstance(model, VestaboardArrayModel):
        board: VestaboardModel = model.board
        colors = [list(row) for row in model.colors]
        # Arrays are drawn as one continuous board unless each Note is framed
        show_frame = entry.options.get(CONF_SHOW_FRAME, False)
    else:
        board = model
        colors = [[model.color]]
        show_frame = model.has_frame

    # A single framed board's size, frame and logo, in inches
    framed = VestaboardModel(board.color, board.model)
    return {
        "device_id": device_id,
        "name": entry.title,
        "type": get_entry_type(entry),
        "model": board.model,
        "rows": model.rows,
        "columns": model.columns,
        # Each board in an array is drawn in its own color
        "board_rows": board.rows,
        "board_columns": board.columns,
        "colors": colors,
        "show_frame": show_frame,
        "frame": {
            "width": framed.width,
            "height": framed.height,
            "border": framed.frame_border,
            "thickness": framed.frame_thickness,
            "logo": logos[board.model],
        },
        "heart": HEART_CODE in model.emoji_map,
        "quiet_hours": coordinator.quiet_hours(),
        "characters": coordinator.data,
    }


@websocket_api.websocket_command({vol.Required("type"): "vestaboard/boards"})
@websocket_api.async_response
async def websocket_boards(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """List the loaded Vestaboards and arrays, with how to draw them."""
    heart, logos = await _async_get_assets(hass)
    device_registry = dr.async_get(hass)
    boards = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        device = device_registry.async_get_device(
            identifiers={(DOMAIN, entry.entry_id)}
        )
        if device is None or (info := _board_info(entry, device.id, logos)) is None:
            continue
        boards.append(info)
    boards.sort(key=lambda board: board["name"].lower())

    connection.send_result(
        msg["id"],
        {
            "boards": boards,
            "themes": {
                color: {
                    "frame": theme.frame,
                    "bit": theme.bit,
                    "text": theme.text,
                    "logo": theme.logo,
                    "colors": theme.color_map,
                }
                for color, theme in COLOR_SCHEMES.items()
            },
            # Physical size of a bit and the spacing between bits, in inches
            "bit": {
                "width": BIT_WIDTH,
                "height": BIT_HEIGHT,
                "gap_x": BIT_WIDTH_SPACING,
                "gap_y": BIT_HEIGHT_SPACING,
            },
            # Index is the character code
            "characters": list(PRINTABLE),
            "heart_image": heart,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "vestaboard/layout",
        vol.Required(CONF_DEVICE_ID): str,
        vol.Required(CONF_MESSAGE): str,
        vol.Optional(CONF_JUSTIFY, default=ALIGN_CENTER): vol.In(ALIGN_HORIZONTAL),
        vol.Optional(CONF_ALIGN, default=ALIGN_CENTER): vol.In(ALIGN_VERTICAL),
    }
)
@callback
def websocket_layout(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Lay out a text message the same way the message action does."""
    try:
        coordinator = async_get_coordinator_by_device_id(hass, msg[CONF_DEVICE_ID])
    except ValueError as err:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, str(err))
        return
    if coordinator.model is None:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Vestaboard model is not known yet"
        )
        return

    vbml = message_vbml(msg[CONF_MESSAGE], msg[CONF_JUSTIFY], msg[CONF_ALIGN])
    try:
        characters = coordinator.model.parse_vbml(vbml)
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, str(err))
        return
    connection.send_result(msg["id"], {"characters": characters})
