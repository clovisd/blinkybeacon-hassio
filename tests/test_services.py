"""Tests for the spin, flash and stop actions."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

import aiohttp
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
import voluptuous as vol

from custom_components.blinkybeacon.api import BeaconStatus
from custom_components.blinkybeacon.const import (
    DOMAIN,
    TIMED_STOP_RETRIES,
    TIMED_STOP_RETRY_INTERVAL,
)

from .conftest import BASE, PORT, setup_integration, status_json

AWAY = "http://192.0.2.11:1337"


@pytest.fixture
def away_entry() -> MockConfigEntry:
    """A config entry for the away team's beacon."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Away beacon",
        data={"host": "192.0.2.11", "port": PORT},
        unique_id="192.0.2.11:1337",
    )


@pytest.fixture
async def home(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> str:
    """Set up the home beacon with a tray that obeys; return its device id."""
    aioclient_mock.get(f"{BASE}/status", json=status_json())
    aioclient_mock.post(f"{BASE}/spin", json=status_json("spin"))
    aioclient_mock.post(f"{BASE}/flash", json=status_json("flash"))
    aioclient_mock.post(f"{BASE}/stop", json=status_json("idle"))
    await setup_integration(hass, mock_config_entry)
    return _device_id(device_registry, mock_config_entry)


def _device_id(device_registry: dr.DeviceRegistry, entry: MockConfigEntry) -> str:
    return dr.async_entries_for_config_entry(device_registry, entry.entry_id)[0].id


def _posts(aioclient_mock: AiohttpClientMocker, url: str) -> int:
    return sum(
        1
        for method, called, *_ in aioclient_mock.mock_calls
        if method == "POST" and str(called) == url
    )


async def _call(hass: HomeAssistant, service: str, **data: object) -> None:
    await hass.services.async_call(DOMAIN, service, data, blocking=True)


async def _wait(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: int
) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_spin_action_spins(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    home: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Spin posts /spin to the chosen beacon and the light follows."""
    await _call(hass, "spin", device_id=home)

    assert not [r for r in caplog.records if "deprecated" in r.getMessage()]

    assert _posts(aioclient_mock, f"{BASE}/spin") == 1
    light = hass.states.get("light.home_beacon")
    assert (light.state, light.attributes["effect"]) == ("on", "spin")


async def test_flash_and_stop_actions(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, home: str
) -> None:
    """Flash and stop post their routes."""
    await _call(hass, "flash", device_id=[home])
    await _call(hass, "stop", device_id=[home])

    assert _posts(aioclient_mock, f"{BASE}/flash") == 1
    assert _posts(aioclient_mock, f"{BASE}/stop") == 1
    assert hass.states.get("light.home_beacon").state == STATE_OFF


async def test_duration_sends_stop_after(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    home: str,
) -> None:
    """A spin with a duration is stopped when the duration is up, not before."""
    await _call(hass, "spin", device_id=home, duration=10)

    await _wait(hass, freezer, 9)
    assert _posts(aioclient_mock, f"{BASE}/stop") == 0

    await _wait(hass, freezer, 1)
    assert _posts(aioclient_mock, f"{BASE}/stop") == 1


async def test_new_command_cancels_pending_stop(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    home: str,
) -> None:
    """A second press within the window is not cut short by the first one's stop."""
    await _call(hass, "spin", device_id=home, duration=10)
    await _wait(hass, freezer, 5)
    await _call(hass, "spin", device_id=home, duration=10)

    await _wait(hass, freezer, 6)
    assert _posts(aioclient_mock, f"{BASE}/stop") == 0

    await _wait(hass, freezer, 4)
    assert _posts(aioclient_mock, f"{BASE}/stop") == 1


async def test_light_turn_off_cancels_pending_stop(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    home: str,
) -> None:
    """Turning the light off replaces the pending stop; no second stop follows."""
    await _call(hass, "spin", device_id=home, duration=10)
    await hass.services.async_call(
        "light", "turn_off", {"entity_id": "light.home_beacon"}, blocking=True
    )

    await _wait(hass, freezer, 20)
    assert _posts(aioclient_mock, f"{BASE}/stop") == 1


def _stop_issue(hass: HomeAssistant, entry: MockConfigEntry) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(
        DOMAIN, f"timed_stop_failed_{entry.entry_id}"
    )


async def test_timed_stop_that_fails_once_is_sent_again(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A timed stop that fails is sent again a few seconds later, until it is taken."""
    aioclient_mock.get(f"{BASE}/status", json=status_json())
    aioclient_mock.post(f"{BASE}/spin", json=status_json("spin"))
    aioclient_mock.post(f"{BASE}/stop", exc=aiohttp.ClientError())
    await setup_integration(hass, mock_config_entry)

    await _call(
        hass,
        "spin",
        device_id=_device_id(device_registry, mock_config_entry),
        duration=10,
    )
    await _wait(hass, freezer, 10)
    assert _posts(aioclient_mock, f"{BASE}/stop") == 1
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Home beacon" in r.getMessage() for r in warnings)

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/status", json=status_json("spin"))
    aioclient_mock.post(f"{BASE}/stop", json=status_json("idle"))
    await _wait(hass, freezer, TIMED_STOP_RETRY_INTERVAL)

    assert _posts(aioclient_mock, f"{BASE}/stop") == 1
    assert hass.states.get("light.home_beacon").state == STATE_OFF
    assert _stop_issue(hass, mock_config_entry) is None
    # Taken: nothing more is sent.
    await _wait(hass, freezer, TIMED_STOP_RETRY_INTERVAL * 3)
    assert _posts(aioclient_mock, f"{BASE}/stop") == 1


async def test_timed_stop_that_keeps_failing_raises_a_repair_naming_the_beacon(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """After the last try the beacon is named in a repair, until a command is taken."""
    aioclient_mock.get(f"{BASE}/status", json=status_json("spin"))
    aioclient_mock.post(f"{BASE}/spin", json=status_json("spin"))
    aioclient_mock.post(f"{BASE}/stop", exc=aiohttp.ClientError())
    await setup_integration(hass, mock_config_entry)
    device_id = _device_id(device_registry, mock_config_entry)

    await _call(hass, "spin", device_id=device_id, duration=10)
    await _wait(hass, freezer, 10)
    for sent in range(1, TIMED_STOP_RETRIES + 1):
        assert _posts(aioclient_mock, f"{BASE}/stop") == sent
        assert _stop_issue(hass, mock_config_entry) is None
        await _wait(hass, freezer, TIMED_STOP_RETRY_INTERVAL)

    assert _posts(aioclient_mock, f"{BASE}/stop") == TIMED_STOP_RETRIES + 1
    issue = _stop_issue(hass, mock_config_entry)
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.translation_key == "timed_stop_failed"
    assert issue.translation_placeholders == {
        "name": "Home beacon",
        "address": "192.0.2.10:1337",
        "tries": str(TIMED_STOP_RETRIES + 1),
    }
    # It is not tried for ever.
    await _wait(hass, freezer, TIMED_STOP_RETRY_INTERVAL * 3)
    assert _posts(aioclient_mock, f"{BASE}/stop") == TIMED_STOP_RETRIES + 1

    # The next command the beacon takes clears it.
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/status", json=status_json())
    aioclient_mock.post(f"{BASE}/stop", json=status_json("idle"))
    await _call(hass, "stop", device_id=device_id)
    assert _stop_issue(hass, mock_config_entry) is None


async def test_newer_command_ends_the_tries_of_a_failed_timed_stop(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A spin sent while a failed stop is being tried again is not cut short by it."""
    aioclient_mock.get(f"{BASE}/status", json=status_json("spin"))
    aioclient_mock.post(f"{BASE}/spin", json=status_json("spin"))
    aioclient_mock.post(f"{BASE}/stop", exc=aiohttp.ClientError())
    await setup_integration(hass, mock_config_entry)
    device_id = _device_id(device_registry, mock_config_entry)

    await _call(hass, "spin", device_id=device_id, duration=10)
    await _wait(hass, freezer, 10)
    assert _posts(aioclient_mock, f"{BASE}/stop") == 1

    await _call(hass, "spin", device_id=device_id)
    await _wait(hass, freezer, TIMED_STOP_RETRY_INTERVAL * 3)

    assert _posts(aioclient_mock, f"{BASE}/stop") == 1
    assert _stop_issue(hass, mock_config_entry) is None


async def test_late_answer_to_a_stop_does_not_cancel_a_newer_timed_spin(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    home: str,
    freezer: FrozenDateTimeFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stop still waiting for its answer when a timed spin is sent leaves the
    spin its timed stop."""
    client = mock_config_entry.runtime_data.client
    answer_stop = asyncio.Event()
    stops_sent = 0
    real_stop = client.stop

    async def slow_stop() -> BeaconStatus:
        nonlocal stops_sent
        stops_sent += 1
        if stops_sent == 1:
            await answer_stop.wait()
        return await real_stop()

    monkeypatch.setattr(client, "stop", slow_stop)

    stop = hass.async_create_task(_call(hass, "stop", device_id=home))
    while not stops_sent:
        await asyncio.sleep(0)
    spin = hass.async_create_task(_call(hass, "spin", device_id=home, duration=10))
    for _ in range(20):
        await asyncio.sleep(0)
    answer_stop.set()
    await asyncio.gather(stop, spin)

    # The spin was the last command sent: the light shows it, and its stop follows.
    assert hass.states.get("light.home_beacon").state == STATE_ON
    assert _posts(aioclient_mock, f"{BASE}/stop") == 1
    await _wait(hass, freezer, 10)
    assert _posts(aioclient_mock, f"{BASE}/stop") == 2
    assert hass.states.get("light.home_beacon").state == STATE_OFF


async def test_timed_stop_due_while_a_newer_command_is_out_is_dropped(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    home: str,
    freezer: FrozenDateTimeFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A timed stop that comes due while a newer spin waits for its answer does
    not stop that spin once it is taken."""
    await _call(hass, "spin", device_id=home, duration=10)
    client = mock_config_entry.runtime_data.client
    answer_spin = asyncio.Event()
    spin_sent = asyncio.Event()
    real_spin = client.spin

    async def slow_spin() -> BeaconStatus:
        spin_sent.set()
        await answer_spin.wait()
        return await real_spin()

    monkeypatch.setattr(client, "spin", slow_spin)

    spin = hass.async_create_task(_call(hass, "spin", device_id=home))
    await spin_sent.wait()
    freezer.tick(timedelta(seconds=10))
    async_fire_time_changed(hass)
    for _ in range(20):
        await asyncio.sleep(0)
    answer_spin.set()
    await spin
    await hass.async_block_till_done()

    assert _posts(aioclient_mock, f"{BASE}/stop") == 0
    assert hass.states.get("light.home_beacon").state == STATE_ON


async def test_unload_sends_pending_stop(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    home: str,
) -> None:
    """Unloading during a timed spin stops the beacon at once, and only once."""
    await _call(hass, "spin", device_id=home, duration=60)

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    assert _posts(aioclient_mock, f"{BASE}/stop") == 1

    await _wait(hass, freezer, 61)
    assert _posts(aioclient_mock, f"{BASE}/stop") == 1


async def test_ha_stop_sends_pending_stop(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    home: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Home Assistant shutting down during a timed spin stops the beacon."""
    await _call(hass, "spin", device_id=home, duration=60)

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()

    assert _posts(aioclient_mock, f"{BASE}/stop") == 1

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_unreachable_raises_cannot_reach(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, home: str
) -> None:
    """A tray that stopped answering fails the action, naming the beacon."""
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{BASE}/spin", exc=aiohttp.ClientError())

    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, "spin", device_id=home)

    assert err.value.translation_key == "cannot_reach"


async def test_unplugged_raises_not_plugged_in(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, home: str
) -> None:
    """A 503 fails the action as an unplugged light."""
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/status", json=status_json(connected=False))
    aioclient_mock.post(
        f"{BASE}/flash", status=503, json={"error": "beacon not connected"}
    )

    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, "flash", device_id=home)

    assert err.value.translation_key == "not_plugged_in"


async def test_unexpected_reply_raises(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, home: str
) -> None:
    """Any other failing reply fails the action as an unexpected reply."""
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{BASE}/stop", status=500, text="boom")

    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, "stop", device_id=home)

    assert err.value.translation_key == "unexpected_reply"


@pytest.mark.parametrize("other_integration", [True, False])
async def test_unknown_device_raises_validation(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
    home: str,
    other_integration: bool,
) -> None:
    """A non-beacon device, or no device at all, is refused before any call."""
    device_id = "not-a-device"
    if other_integration:
        other = MockConfigEntry(domain="zha")
        other.add_to_hass(hass)
        device_id = device_registry.async_get_or_create(
            config_entry_id=other.entry_id, identifiers={("zha", "button")}
        ).id

    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "spin", device_id=[home, device_id])

    assert err.value.translation_key == "unknown_device"
    assert _posts(aioclient_mock, f"{BASE}/spin") == 0


async def test_not_loaded_entry_raises_cannot_reach(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """A beacon whose tray was down at startup fails the action, not skips it."""
    mock_config_entry.add_to_hass(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, mock_config_entry.entry_id)},
    )
    aioclient_mock.get(f"{BASE}/status", exc=aiohttp.ClientError())
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, "spin", device_id=device.id)

    assert err.value.translation_key == "cannot_reach"
    assert err.value.translation_placeholders == {
        "name": "Home beacon",
        "address": "192.0.2.10:1337",
    }


async def test_two_beacons_one_fails(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
    away_entry: MockConfigEntry,
    home: str,
) -> None:
    """Every beacon is tried; the error names the ones that failed."""
    aioclient_mock.get(f"{AWAY}/status", json=status_json())
    aioclient_mock.post(
        f"{AWAY}/spin", status=503, json={"error": "beacon not connected"}
    )
    await setup_integration(hass, away_entry)
    away = _device_id(device_registry, away_entry)

    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, "spin", device_id=[home, away])

    assert _posts(aioclient_mock, f"{BASE}/spin") == 1
    assert err.value.translation_key == "commands_failed"
    assert err.value.translation_placeholders == {"names": "Away beacon"}


@pytest.mark.parametrize("duration", [0, 3601])
async def test_duration_out_of_range(
    hass: HomeAssistant, home: str, duration: int
) -> None:
    """Durations outside 1-3600 seconds are refused."""
    with pytest.raises(vol.Invalid):
        await _call(hass, "spin", device_id=home, duration=duration)


async def test_failed_command_keeps_pending_stop(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    home: str,
) -> None:
    """A press that fails does not cancel the stop an earlier press scheduled."""
    await _call(hass, "spin", device_id=home, duration=10)
    await _wait(hass, freezer, 5)
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/status", json=status_json("spin"))
    aioclient_mock.post(f"{BASE}/flash", exc=aiohttp.ClientError())
    aioclient_mock.post(f"{BASE}/stop", json=status_json("idle"))

    with pytest.raises(HomeAssistantError):
        await _call(hass, "flash", device_id=home, duration=60)

    await _wait(hass, freezer, 5)
    assert _posts(aioclient_mock, f"{BASE}/stop") == 1
