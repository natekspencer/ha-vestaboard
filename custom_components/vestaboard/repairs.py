"""Repairs for the Vestaboard integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.repairs import FlowType, RepairsFlow, RepairsFlowResult
from homeassistant.config_entries import SOURCE_RECONFIGURE, ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_LAYOUT, DOMAIN
from .helpers import is_array_entry

ISSUE_ARRAY_BOARD_DISABLED = "array_board_disabled"
ISSUE_ARRAY_MISSING_BOARD = "array_missing_board"


def array_issue_id(issue: str, array_entry_id: str) -> str:
    """Return the repair issue id for an issue with an array."""
    return f"{issue}_{array_entry_id}"


class ArrayRepairFlow(RepairsFlow):
    """Fix an array that has lost a Note or has a disabled Note.

    Offers to reconfigure or delete the array, and to enable disabled Notes.
    """

    def __init__(self, entry_id: str, issue: str) -> None:
        """Initialize."""
        self.entry_id = entry_id
        self.issue = issue

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> RepairsFlowResult:
        """Offer the ways to fix the array."""
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        if entry is None or not is_array_entry(entry):
            return self.async_abort(reason="array_not_found")
        placeholders = {"array": entry.title}
        menu_options = ["reconfigure", "delete"]
        if self.issue == ISSUE_ARRAY_BOARD_DISABLED:
            disabled = self._disabled_members()
            placeholders["boards"] = ", ".join(member.title for member in disabled)
            if disabled:
                menu_options.insert(0, "enable")
        return self.async_show_menu(
            step_id="init",
            menu_options=menu_options,
            description_placeholders=placeholders,
        )

    async def async_step_enable(
        self, user_input: dict[str, Any] | None = None
    ) -> RepairsFlowResult:
        """Enable the array's disabled Notes.

        Each enabled Note reloads the array once it's set up, which clears the
        issue.
        """
        for member in self._disabled_members():
            await self.hass.config_entries.async_set_disabled_by(member.entry_id, None)
        return self.async_create_entry(data={})

    def _disabled_members(self) -> list[ConfigEntry]:
        """Return the array's member entries that are disabled."""
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        members = [
            self.hass.config_entries.async_get_entry(entry_id)
            for row in entry.data[CONF_LAYOUT]
            for entry_id in row
        ]
        return [member for member in members if member and member.disabled_by]

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
    for issue in (ISSUE_ARRAY_MISSING_BOARD, ISSUE_ARRAY_BOARD_DISABLED):
        if data and issue_id == array_issue_id(issue, str(data["entry_id"])):
            return ArrayRepairFlow(str(data["entry_id"]), issue)
    raise ValueError(f"Unknown repair {issue_id}")
