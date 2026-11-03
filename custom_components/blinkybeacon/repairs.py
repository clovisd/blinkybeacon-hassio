"""The notice that a USB beacon is missing from its port, and its fix."""

from __future__ import annotations

from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
import voluptuous as vol

from .const import CONF_USB_PORT, DOMAIN
from .coordinator import BlinkyBeaconCoordinator

ISSUE_USB_MISSING = "usb_missing"


def missing_issue_id(entry_id: str) -> str:
    """The ID of the notice that an entry's beacon is missing."""
    return f"{ISSUE_USB_MISSING}_{entry_id}"


@callback
def async_track_missing(
    hass: HomeAssistant, coordinator: BlinkyBeaconCoordinator
) -> None:
    """Keep the notice raised while the beacon is missing, until it is unloaded."""
    entry = coordinator.config_entry
    issue_id = missing_issue_id(entry.entry_id)

    @callback
    def _async_update() -> None:
        if coordinator.data.connected:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
            return
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            data={"entry_id": entry.entry_id},
            is_fixable=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_USB_MISSING,
            translation_placeholders={
                "name": entry.title,
                "port": entry.data[CONF_USB_PORT],
            },
        )

    _async_update()
    entry.async_on_unload(coordinator.async_add_listener(_async_update))
    entry.async_on_unload(lambda: ir.async_delete_issue(hass, DOMAIN, issue_id))


class RemoveMissingBeaconFlow(RepairsFlow):
    """Removes a missing beacon once the user confirms it is not coming back."""

    def __init__(self, entry_id: str) -> None:
        self._entry_id = entry_id

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Ask before removing."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Remove the beacon's entry, with its device and entities."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_create_entry(data={})
        if user_input is not None:
            await self.hass.config_entries.async_remove(entry.entry_id)
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "name": entry.title,
                "port": entry.data[CONF_USB_PORT],
            },
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """The fix for a missing beacon: remove it."""
    return RemoveMissingBeaconFlow(str(data["entry_id"]) if data else "")
