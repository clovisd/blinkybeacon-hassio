"""Tests for adding a beacon plugged into Home Assistant by hand."""

from __future__ import annotations

from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_IGNORE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.blinkybeacon.const import DOMAIN

from .conftest import BASE, HOST, PORT, status_json
from .fake_usb import FLASH, STOP, FakeUsb, tick


async def _start(hass: HomeAssistant) -> dict[str, Any]:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


async def _to_usb(hass: HomeAssistant) -> dict[str, Any]:
    result = await _start(hass)
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "usb"}
    )


async def _to_name(hass: HomeAssistant, port: str = "1-1") -> dict[str, Any]:
    result = await _to_usb(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"usb_port": port}
    )
    await hass.async_block_till_done()
    return result


def _field(result: dict[str, Any], name: str) -> tuple[Any, Any]:
    """The schema key and validator of a form field."""
    return next(
        (key, value)
        for key, value in result["data_schema"].schema.items()
        if key == name
    )


def _ignored(port: str) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, source=SOURCE_IGNORE, unique_id=f"usb:{port}", data={}
    )


async def test_menu_when_a_usb_beacon_waits(
    hass: HomeAssistant, fake_usb: FakeUsb
) -> None:
    """With an unnamed beacon plugged in, the first step asks where it is."""
    fake_usb.plug("1-1")

    result = await _start(hass)

    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["tray", "usb"]


async def test_tray_form_when_no_usb_beacon_waits(hass: HomeAssistant) -> None:
    """With none plugged in, the first step is the tray form."""
    result = await _start(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "tray"


async def test_tray_from_the_menu(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, fake_usb: FakeUsb
) -> None:
    """Choosing the tray from the menu adds a tray as before."""
    fake_usb.plug("1-1")
    aioclient_mock.get(f"{BASE}/status", json=status_json())
    result = await _start(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "tray"}
    )
    assert result["step_id"] == "tray"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": HOST, "port": PORT, "name": "Home beacon"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"host": HOST, "port": PORT}


async def test_usb_lists_unnamed_ports(
    hass: HomeAssistant, fake_usb: FakeUsb, usb_entry: MockConfigEntry
) -> None:
    """Ports with a named beacon are left out; an ignored offer is listed."""
    fake_usb.plug("1-1", "hidraw0")
    fake_usb.plug("1-2", "hidraw1")
    fake_usb.plug("1-3.1", "hidraw2")
    usb_entry.add_to_hass(hass)
    _ignored("1-2").add_to_hass(hass)

    result = await _to_usb(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "usb"
    _, ports = _field(result, "usb_port")
    assert ports.container == {"1-2": "USB port 1-2", "1-3.1": "USB port 1-3.1"}


async def test_naming_flashes_then_adds_the_beacon(
    hass: HomeAssistant, fake_usb: FakeUsb, freezer: FrozenDateTimeFactory
) -> None:
    """The beacon flashes while it is named, stops on submit, and is added."""
    fake_usb.plug("1-1")

    result = await _to_name(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "name"
    assert result["description_placeholders"] == {"port": "1-1"}
    key, _ = _field(result, "name")
    assert key.default() == "Beacon on USB port 1-1"
    assert fake_usb.written() == [STOP, FLASH]

    await tick(hass, freezer, 5)
    assert fake_usb.written() == [STOP, FLASH, FLASH]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "  Team A beacon "}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Team A beacon"
    assert result["data"] == {"usb_port": "1-1"}
    assert result["result"].unique_id == "usb:1-1"
    assert fake_usb.written() == [STOP, FLASH, FLASH, STOP, STOP]
    assert hass.states.get("light.team_a_beacon").state == "off"


async def test_closing_the_naming_step_stops_the_beacon(
    hass: HomeAssistant, fake_usb: FakeUsb, freezer: FrozenDateTimeFactory
) -> None:
    """A naming step closed without an answer stops the beacon for good."""
    fake_usb.plug("1-1")
    result = await _to_name(hass)

    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()
    await tick(hass, freezer, 10)

    assert fake_usb.written() == [STOP, FLASH, STOP]
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_blank_name_is_refused(hass: HomeAssistant, fake_usb: FakeUsb) -> None:
    """A blank name keeps the form open, and the beacon keeps flashing."""
    fake_usb.plug("1-1")
    result = await _to_name(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "   "}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"name": "name_required"}
    assert fake_usb.written() == [STOP, FLASH]
    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()


async def test_no_usb_beacon_left_shows_the_tray_form(
    hass: HomeAssistant, fake_usb: FakeUsb
) -> None:
    """A beacon unplugged before its port is listed leads to the tray form."""
    fake_usb.plug("1-1")
    result = await _start(hass)
    fake_usb.unplug()

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "usb"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "tray"
    assert result["errors"] == {"base": "no_usb_beacon"}


async def test_port_emptied_before_it_is_picked(
    hass: HomeAssistant, fake_usb: FakeUsb
) -> None:
    """A port that empties while the list is shown is refused, and the list redone."""
    fake_usb.plug("1-1", "hidraw0")
    fake_usb.plug("1-2", "hidraw1")
    result = await _to_usb(hass)
    fake_usb.unplug("hidraw0")

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"usb_port": "1-1"}
    )

    assert result["step_id"] == "usb"
    assert result["errors"] == {"base": "usb_beacon_gone"}
    _, ports = _field(result, "usb_port")
    assert ports.container == {"1-2": "USB port 1-2"}


async def test_port_added_meanwhile_aborts(
    hass: HomeAssistant, fake_usb: FakeUsb, usb_entry: MockConfigEntry
) -> None:
    """A port added by another flow while this one names it aborts, and stops."""
    fake_usb.plug("1-1")
    result = await _to_name(hass)
    usb_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Team B beacon"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert fake_usb.written() == [STOP, FLASH, STOP]


async def test_ignored_offer_added_by_hand(
    hass: HomeAssistant, fake_usb: FakeUsb
) -> None:
    """A beacon whose offer was ignored can still be added by hand."""
    fake_usb.plug("1-1")
    _ignored("1-1").add_to_hass(hass)
    result = await _to_name(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Team A beacon"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    entries = hass.config_entries.async_entries(DOMAIN, include_ignore=True)
    assert [(e.source, e.unique_id) for e in entries] == [("user", "usb:1-1")]


async def test_reconfigure_a_usb_beacon_aborts(
    hass: HomeAssistant, usb_entry: MockConfigEntry
) -> None:
    """A USB beacon has no address to change; reconfigure says so."""
    usb_entry.add_to_hass(hass)

    result = await usb_entry.start_reconfigure_flow(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "usb_not_reconfigurable"
    assert usb_entry.data == {"usb_port": "1-1"}


async def test_naming_flash_stops_after_two_minutes(
    hass: HomeAssistant, fake_usb: FakeUsb, freezer: FrozenDateTimeFactory
) -> None:
    """A naming form left open stops the flash 2 minutes after it was shown."""
    fake_usb.plug("1-1")
    result = await _to_name(hass)

    await tick(hass, freezer, 119)
    assert fake_usb.written()[-1] == FLASH

    await tick(hass, freezer, 1)
    assert fake_usb.written()[-1] == STOP
    written = len(fake_usb.written())

    await tick(hass, freezer, 30)
    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()
    assert len(fake_usb.written()) == written


async def test_showing_the_naming_form_again_restarts_the_two_minutes(
    hass: HomeAssistant, fake_usb: FakeUsb, freezer: FrozenDateTimeFactory
) -> None:
    """Each time the naming form is shown, the flash runs 2 more minutes."""
    fake_usb.plug("1-1")
    result = await _to_name(hass)
    await tick(hass, freezer, 60)

    # Opening the form again in the UI runs its step again with no input.
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["step_id"] == "name"
    await tick(hass, freezer, 61)
    assert fake_usb.written()[-1] == FLASH

    await tick(hass, freezer, 59)
    assert fake_usb.written()[-1] == STOP
    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()
