"""Tests for a beacon plugged into Home Assistant: its device, entities, actions."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryDisabler, ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.blinkybeacon.const import DOMAIN
from custom_components.blinkybeacon.coordinator import beacon_error

from .conftest import BASE, setup_integration, status_json
from .fake_usb import FLASH, SPIN, STOP, FakeUsb, tick

LIGHT = "light.team_a_beacon"
SENSOR = "binary_sensor.team_a_beacon_usb_connected"


def _device_id(device_registry: dr.DeviceRegistry, entry: MockConfigEntry) -> str:
    return dr.async_entries_for_config_entry(device_registry, entry.entry_id)[0].id


async def _call(hass: HomeAssistant, service: str, **data: object) -> None:
    await hass.services.async_call(DOMAIN, service, data, blocking=True)


async def test_setup_and_unload(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    usb_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A plugged-in beacon loads idle; unloading stops it and ends the keepalive."""
    fake_usb.plug("1-1")

    await setup_integration(hass, usb_entry)

    assert usb_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(LIGHT).state == STATE_OFF
    assert hass.states.get(SENSOR).state == STATE_ON
    assert fake_usb.written() == [STOP]

    assert await hass.config_entries.async_unload(usb_entry.entry_id)
    await tick(hass, freezer, 10)

    assert usb_entry.state is ConfigEntryState.NOT_LOADED
    assert fake_usb.written() == [STOP, STOP]


async def test_missing_at_setup_loads_unavailable(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    usb_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A beacon not plugged in at startup still loads, shown missing until it is."""
    await setup_integration(hass, usb_entry)

    assert usb_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(LIGHT).state == STATE_UNAVAILABLE
    assert hass.states.get(SENSOR).state == STATE_OFF

    fake_usb.plug("1-1")
    await tick(hass, freezer, 5)
    await tick(hass, freezer, 5)

    assert hass.states.get(LIGHT).state == STATE_OFF
    assert hass.states.get(SENSOR).state == STATE_ON


async def test_unplug_and_replug(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    usb_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Unplugged, the light is unavailable; plugged back, it returns idle."""
    fake_usb.plug("1-1", "hidraw0")
    await setup_integration(hass, usb_entry)
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": LIGHT}, blocking=True
    )

    fake_usb.unplug("hidraw0")
    await tick(hass, freezer, 5)

    assert hass.states.get(LIGHT).state == STATE_UNAVAILABLE
    assert hass.states.get(SENSOR).state == STATE_OFF

    fake_usb.plug("1-1", "hidraw1")
    await tick(hass, freezer, 5)
    await tick(hass, freezer, 5)

    assert hass.states.get(LIGHT).state == STATE_OFF
    assert hass.states.get(SENSOR).state == STATE_ON
    assert fake_usb.written("hidraw1")[0] == STOP


async def test_quick_replug_is_never_shown_missing(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    usb_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Plugged straight back in, the beacon raises no notice and keeps its mode."""
    fake_usb.plug("1-1")
    await setup_integration(hass, usb_entry)
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": LIGHT}, blocking=True
    )
    issue_id = f"usb_missing_{usb_entry.entry_id}"
    issues_raised: list[str] = []
    light_states: list[str] = []

    @callback
    def _issue_changed(event: Event[ir.EventIssueRegistryUpdatedData]) -> None:
        if event.data["issue_id"] == issue_id:
            issues_raised.append(event.data["action"])

    @callback
    def _light_changed(event: Event[EventStateChangedData]) -> None:
        if (state := event.data["new_state"]) is not None:
            light_states.append(state.state)

    hass.bus.async_listen(ir.EVENT_REPAIRS_ISSUE_REGISTRY_UPDATED, _issue_changed)
    async_track_state_change_event(hass, LIGHT, _light_changed)

    fake_usb.unplug()
    fake_usb.plug("1-1")
    for _ in range(3):
        await tick(hass, freezer, 5)
        assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
        assert hass.states.get(LIGHT).state != STATE_UNAVAILABLE

    assert issues_raised == []
    assert STATE_UNAVAILABLE not in light_states
    assert hass.states.get(LIGHT).state == STATE_ON
    assert hass.states.get(SENSOR).state == STATE_ON
    assert fake_usb.written() == [SPIN, SPIN, SPIN]


async def test_light_turn_on_spins(
    hass: HomeAssistant, fake_usb: FakeUsb, usb_entry: MockConfigEntry
) -> None:
    """Turning the light on spins the beacon, and the state follows at once."""
    fake_usb.plug("1-1")
    await setup_integration(hass, usb_entry)

    await hass.services.async_call(
        "light", "turn_on", {"entity_id": LIGHT}, blocking=True
    )

    assert fake_usb.written() == [STOP, SPIN]
    light = hass.states.get(LIGHT)
    assert (light.state, light.attributes["effect"]) == (STATE_ON, "spin")


async def test_actions_and_duration(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    usb_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Spin, flash and stop drive the beacon; a duration stops it on time."""
    fake_usb.plug("1-1")
    await setup_integration(hass, usb_entry)
    device = _device_id(device_registry, usb_entry)

    await _call(hass, "flash", device_id=device)
    await _call(hass, "stop", device_id=device)
    assert fake_usb.written() == [STOP, FLASH, STOP]

    await _call(hass, "spin", device_id=device, duration=10)
    await tick(hass, freezer, 9)
    assert fake_usb.written()[-1] == SPIN
    assert hass.states.get(LIGHT).state == STATE_ON

    await tick(hass, freezer, 1)
    assert fake_usb.written()[-1] == STOP
    assert hass.states.get(LIGHT).state == STATE_OFF


async def test_action_on_missing_beacon_names_it(
    hass: HomeAssistant,
    usb_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """An action on a beacon that is not plugged in fails, naming it and its port."""
    await setup_integration(hass, usb_entry)

    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, "spin", device_id=_device_id(device_registry, usb_entry))

    assert err.value.translation_key == "usb_not_plugged_in"
    assert err.value.translation_placeholders == {
        "name": "Team A beacon",
        "port": "1-1",
    }
    assert str(err.value) == (
        "Team A beacon on USB port 1-1 did not take the command: it is not plugged"
        " in, or Home Assistant cannot open it (the log names the error)"
    )


async def test_action_on_not_loaded_beacon_names_it(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    device_registry: dr.DeviceRegistry,
) -> None:
    """A USB beacon whose entry is not loaded fails the action, never skips it."""
    fake_usb.plug("1-1")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Team A beacon",
        data={"usb_port": "1-1"},
        unique_id="usb:1-1",
        disabled_by=ConfigEntryDisabler.USER,
    )
    entry.add_to_hass(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, entry.entry_id)}
    )
    assert await async_setup_component(hass, DOMAIN, {})

    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, "spin", device_id=device.id)

    assert err.value.translation_key == "usb_not_loaded"
    assert err.value.translation_placeholders == {
        "name": "Team A beacon",
        "port": "1-1",
    }
    assert fake_usb.written() == []


async def test_device_registered(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    usb_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """A USB beacon is a device named as given, with no tray settings page."""
    fake_usb.plug("1-1")
    await setup_integration(hass, usb_entry)

    devices = dr.async_entries_for_config_entry(device_registry, usb_entry.entry_id)
    assert len(devices) == 1
    assert devices[0].name == "Team A beacon"
    assert devices[0].model == "USB beacon"
    assert devices[0].configuration_url is None


async def test_tray_and_usb_beacons_together(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    usb_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """One action reaches a tray and a USB beacon; the error names the one missing."""
    aioclient_mock.get(f"{BASE}/status", json=status_json())
    aioclient_mock.post(f"{BASE}/spin", json=status_json("spin"))
    await setup_integration(hass, mock_config_entry)
    await setup_integration(hass, usb_entry)

    with pytest.raises(HomeAssistantError) as err:
        await _call(
            hass,
            "spin",
            device_id=[
                _device_id(device_registry, mock_config_entry),
                _device_id(device_registry, usb_entry),
            ],
        )

    assert err.value.translation_key == "commands_failed"
    assert err.value.translation_placeholders == {"names": "Team A beacon"}
    assert hass.states.get("light.home_beacon").attributes["effect"] == "spin"


def test_error_without_usb_text_names_the_beacon(usb_entry: MockConfigEntry) -> None:
    """An error with no USB text of its own still names the beacon and its port."""
    err = beacon_error(usb_entry, "unexpected_reply")

    assert err.translation_key == "usb_not_plugged_in"
    assert err.translation_placeholders == {"name": "Team A beacon", "port": "1-1"}
