"""Tests for the notice that a USB beacon is missing, and its fix."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.blinkybeacon.const import DOMAIN

from .conftest import BASE, setup_integration, status_json
from .fake_usb import FakeUsb, tick


def _issue(hass: HomeAssistant, entry: MockConfigEntry) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, f"usb_missing_{entry.entry_id}")


async def test_raised_when_the_port_empties_and_cleared_on_return(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    usb_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The notice names the beacon and its port, and clears once it is back."""
    fake_usb.plug("1-1")
    await setup_integration(hass, usb_entry)
    assert _issue(hass, usb_entry) is None

    fake_usb.unplug()
    await tick(hass, freezer, 5)

    issue = _issue(hass, usb_entry)
    assert issue is not None
    assert issue.translation_key == "usb_missing"
    assert issue.translation_placeholders == {"name": "Team A beacon", "port": "1-1"}
    assert issue.is_fixable
    assert issue.severity is ir.IssueSeverity.WARNING

    fake_usb.plug("1-1")
    await tick(hass, freezer, 5)
    await tick(hass, freezer, 5)

    assert _issue(hass, usb_entry) is None


async def test_raised_at_startup_when_missing(
    hass: HomeAssistant, usb_entry: MockConfigEntry
) -> None:
    """A beacon missing when Home Assistant starts has its notice at once."""
    await setup_integration(hass, usb_entry)

    assert _issue(hass, usb_entry) is not None


async def test_fix_removes_the_beacon(
    hass: HomeAssistant,
    usb_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Confirming the fix removes the beacon's entry and device, and the notice."""
    await setup_integration(hass, usb_entry)
    assert await async_setup_component(hass, "repairs", {})
    flows = repairs_flow_manager(hass)

    result = await flows.async_init(
        DOMAIN, context={"issue_id": f"usb_missing_{usb_entry.entry_id}"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"] == {
        "name": "Team A beacon",
        "port": "1-1",
    }

    result = await flows.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert hass.config_entries.async_get_entry(usb_entry.entry_id) is None
    assert not dr.async_entries_for_config_entry(device_registry, usb_entry.entry_id)
    assert _issue(hass, usb_entry) is None


async def test_cleared_on_unload(
    hass: HomeAssistant, usb_entry: MockConfigEntry
) -> None:
    """An unloaded beacon carries no notice; it is raised again if still missing."""
    await setup_integration(hass, usb_entry)

    assert await hass.config_entries.async_unload(usb_entry.entry_id)
    assert _issue(hass, usb_entry) is None

    assert await hass.config_entries.async_setup(usb_entry.entry_id)
    assert _issue(hass, usb_entry) is not None


async def test_tray_never_raises_it(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A tray whose light is unplugged shows it on its sensor, with no notice."""
    aioclient_mock.get(f"{BASE}/status", json=status_json(connected=False))

    await setup_integration(hass, mock_config_entry)

    assert not [
        issue
        for (domain, _), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN
    ]
