"""Tests for offering a beacon as soon as it is plugged into Home Assistant."""

from __future__ import annotations

from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import (
    SOURCE_IGNORE,
    SOURCE_INTEGRATION_DISCOVERY,
    SOURCE_USER,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.blinkybeacon.const import DOMAIN

from .conftest import BASE, setup_integration, status_json
from .fake_usb import FLASH, STOP, FakeUsb, tick


@pytest.fixture
async def tray(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> MockConfigEntry:
    """A loaded tray entry, so the scan runs; set up on the frozen clock."""
    aioclient_mock.get(f"{BASE}/status", json=status_json())
    await setup_integration(hass, mock_config_entry)
    return mock_config_entry


def _offers(hass: HomeAssistant) -> list[dict[str, Any]]:
    return [
        flow
        for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        if flow["context"]["source"] == SOURCE_INTEGRATION_DISCOVERY
    ]


async def test_offered_within_ten_seconds(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    tray: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A beacon plugged in is offered by its port, and nothing lights up yet."""
    fake_usb.plug("1-2")

    await tick(hass, freezer, 9)
    assert _offers(hass) == []

    await tick(hass, freezer, 1)
    [offer] = _offers(hass)
    assert offer["step_id"] == "discovery_confirm"
    assert offer["context"]["unique_id"] == "usb:1-2"
    assert offer["context"]["title_placeholders"] == {"port": "1-2"}
    assert fake_usb.written() == []


async def test_not_offered_without_a_loaded_entry(
    hass: HomeAssistant, fake_usb: FakeUsb, freezer: FrozenDateTimeFactory
) -> None:
    """With no beacon set up, nothing scans; the beacon is added by hand."""
    fake_usb.plug("1-1")

    await tick(hass, freezer, 30)

    assert _offers(hass) == []


async def test_offered_once(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    tray: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A port with an offer waiting is not offered again."""
    fake_usb.plug("1-2")

    for _ in range(3):
        await tick(hass, freezer, 10)

    assert len(_offers(hass)) == 1


async def test_named_and_ignored_ports_not_offered(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    usb_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A port that has an entry, or whose offer was ignored, is not offered."""
    fake_usb.plug("1-1", "hidraw0")
    fake_usb.plug("1-2", "hidraw1")
    MockConfigEntry(
        domain=DOMAIN, source=SOURCE_IGNORE, unique_id="usb:1-2", data={}
    ).add_to_hass(hass)
    await setup_integration(hass, usb_entry)

    await tick(hass, freezer, 10)

    assert _offers(hass) == []


async def test_scan_ends_with_the_last_loaded_entry(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    tray: MockConfigEntry,
    usb_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The scan runs while any entry is loaded, and stops after the last one."""
    fake_usb.plug("1-1", "hidraw0")
    await setup_integration(hass, usb_entry)
    assert await hass.config_entries.async_unload(usb_entry.entry_id)
    fake_usb.plug("1-2", "hidraw1")

    await tick(hass, freezer, 10)
    [offer] = _offers(hass)
    hass.config_entries.flow.async_abort(offer["flow_id"])

    assert await hass.config_entries.async_unload(tray.entry_id)
    await tick(hass, freezer, 10)
    assert _offers(hass) == []


async def test_offer_flashes_on_the_naming_step_and_adds(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    tray: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Opening the offer goes to the naming step, which flashes the beacon."""
    fake_usb.plug("1-1")
    await tick(hass, freezer, 10)
    [offer] = _offers(hass)

    result = await hass.config_entries.flow.async_configure(offer["flow_id"], {})
    await hass.async_block_till_done()

    assert result["step_id"] == "name"
    assert fake_usb.written() == [STOP, FLASH]

    result = await hass.config_entries.flow.async_configure(
        offer["flow_id"], {"name": "Team A beacon"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "usb:1-1"
    assert result["result"].source == SOURCE_INTEGRATION_DISCOVERY
    assert fake_usb.written() == [STOP, FLASH, STOP, STOP]


async def test_offer_opened_after_unplug_aborts(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    tray: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """An offer opened after its beacon was unplugged says so and closes."""
    fake_usb.plug("1-1")
    await tick(hass, freezer, 10)
    [offer] = _offers(hass)
    fake_usb.unplug()

    # Opening a waiting flow in the UI runs its step again with no input.
    result = await hass.config_entries.flow.async_configure(offer["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "usb_beacon_gone"
    assert result["description_placeholders"] == {"port": "1-1"}


async def test_adding_by_hand_closes_the_offer(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    tray: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A beacon added by hand while it is offered leaves no offer behind."""
    fake_usb.plug("1-1")
    await tick(hass, freezer, 10)
    assert len(_offers(hass)) == 1

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "usb"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"usb_port": "1-1"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Team A beacon"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _offers(hass) == []


async def test_offer_for_a_named_port_aborts(
    hass: HomeAssistant, usb_entry: MockConfigEntry
) -> None:
    """A second set-up for a port that has an entry is aborted."""
    usb_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_INTEGRATION_DISCOVERY},
        data={"usb_port": "1-1"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_port_being_named_by_hand_is_not_offered(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    tray: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A beacon being named by hand is not offered a second time meanwhile."""
    fake_usb.plug("1-1")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "usb"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"usb_port": "1-1"}
    )
    assert result["step_id"] == "name"

    await tick(hass, freezer, 10)

    assert _offers(hass) == []
    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()
