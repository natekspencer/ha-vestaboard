"""Tests for the Vestaboard config flow."""

from __future__ import annotations

from custom_components.vestaboard.const import (
    COLOR_BLACK,
    CONF_BOARD_MODEL,
    CONF_ENTRY_TYPE,
    CONF_HEART,
    CONF_MODEL,
    CONF_SHOW_FRAME,
    DOMAIN,
    ENTRY_TYPE_VIRTUAL,
)
from custom_components.vestaboard.vestaboard_model import MODEL_FLAGSHIP, MODEL_NOTE
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from . import setup_virtual_board


async def test_user_menu_without_boards(hass: HomeAssistant) -> None:
    """Test arrays aren't offered until there are boards to put in one."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["device", "virtual"]


async def test_user_menu_offers_array(hass: HomeAssistant) -> None:
    """Test arrays are offered once there are two Notes."""
    await setup_virtual_board(hass, "Note 1", MODEL_NOTE)
    await setup_virtual_board(hass, "Note 2", MODEL_NOTE)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["menu_options"] == ["device", "virtual", "array"]


async def test_user_menu_arrays_need_notes(hass: HomeAssistant) -> None:
    """Test Flagships don't count towards an array."""
    await setup_virtual_board(hass, "Flagship 1")
    await setup_virtual_board(hass, "Flagship 2")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["menu_options"] == ["device", "virtual"]


async def test_virtual_flagship(hass: HomeAssistant) -> None:
    """Test setting up a virtual Flagship."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "virtual"}
    )
    assert result["step_id"] == "virtual"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Kitchen", CONF_BOARD_MODEL: MODEL_FLAGSHIP}
    )
    assert result["step_id"] == "appearance"

    options = {CONF_MODEL: COLOR_BLACK, CONF_HEART: True, CONF_SHOW_FRAME: False}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], options)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Kitchen"
    assert result["data"] == {
        CONF_ENTRY_TYPE: ENTRY_TYPE_VIRTUAL,
        CONF_BOARD_MODEL: MODEL_FLAGSHIP,
    }
    assert result["options"] == options


async def test_virtual_note_has_no_heart(hass: HomeAssistant) -> None:
    """Test the heart is only offered on a Flagship."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "virtual"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Desk", CONF_BOARD_MODEL: MODEL_NOTE}
    )

    assert result["step_id"] == "appearance"
    assert CONF_HEART not in result["data_schema"].schema
