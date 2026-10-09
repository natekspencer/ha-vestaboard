"""Repairs for the Vestaboard integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.repairs import FlowType, RepairsFlow, RepairsFlowResult
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .helpers import is_array_entry

ISSUE_ARRAY_MISSING_BOARD = "array_missing_board"


class ArrayMissingBoardRepairFlow(RepairsFlow):
    """Reconfigure an array that has lost a Note, or delete it."""

    def __init__(self, entry_id: str) -> None:
        """Initialize."""
        self.entry_id = entry_id

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> RepairsFlowResult:
        """Offer to reconfigure or delete the array."""
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        if entry is None or not is_array_entry(entry):
            return self.async_abort(reason="array_not_found")
        return self.async_show_menu(
            step_id="init",
            menu_options=["reconfigure", "delete"],
            description_placeholders={"array": entry.title},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> RepairsFlowResult:
        """Hand off to the array's reconfigure flow.

        The issue stays open until the reconfigured array sets up successfully,
        which deletes it.
        """
        next_flow = await self.hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_RECONFIGURE, "entry_id": self.entry_id},
        )
        return self.async_abort(
            reason="reconfigure",
            next_flow=(FlowType.CONFIG_FLOW, next_flow["flow_id"]),
        )

    async def async_step_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> RepairsFlowResult:
        """Confirm deleting the array."""
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        if entry is None:
            return self.async_abort(reason="array_not_found")
        if user_input is not None:
            await self.hass.config_entries.async_remove(entry.entry_id)
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="delete", description_placeholders={"array": entry.title}
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create a flow to fix an issue."""
    if issue_id.startswith(ISSUE_ARRAY_MISSING_BOARD) and data:
        return ArrayMissingBoardRepairFlow(str(data["entry_id"]))
    raise ValueError(f"Unknown repair {issue_id}")
