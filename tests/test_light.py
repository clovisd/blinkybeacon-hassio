"""Tests for the beacon as a light."""

from __future__ import annotations

import logging

from homeassistant.components.light import ATTR_EFFECT
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from .conftest import BASE, setup_integration, status_json

ENTITY_ID = "light.home_beacon"


async def _setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    entry: MockConfigEntry,
    state: str = "idle",
    connected: bool = True,
) -> None:
    aioclient_mock.get(f"{BASE}/status", json=status_json(state, connected))
    await setup_integration(hass, entry)


def _posts(aioclient_mock: AiohttpClientMocker) -> list[str]:
    return [
        str(url) for method, url, *_ in aioclient_mock.mock_calls if method == "POST"
    ]


async def _light(hass: HomeAssistant, service: str, **data: object) -> None:
    await hass.services.async_call(
        "light", service, {"entity_id": ENTITY_ID, **data}, blocking=True
    )


@pytest.mark.parametrize(
    ("state", "expected", "effect"),
    [
        ("idle", STATE_OFF, None),
        ("spin", STATE_ON, "spin"),
        ("flash", STATE_ON, "flash"),
    ],
)
async def test_light_reflects_state(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    state: str,
    expected: str,
    effect: str | None,
) -> None:
    """Idle is off; spin and flash are on with that effect."""
    await _setup(hass, aioclient_mock, mock_config_entry, state)

    light = hass.states.get(ENTITY_ID)
    assert light.state == expected
    assert light.attributes.get(ATTR_EFFECT) == effect
    assert light.attributes["effect_list"] == ["spin", "flash"]


async def test_light_unknown_state_is_on_without_effect(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A state a newer tray might report is on, with no effect, and no error."""
    await _setup(hass, aioclient_mock, mock_config_entry, "test_flash")

    light = hass.states.get(ENTITY_ID)
    assert light.state == STATE_ON
    assert light.attributes.get(ATTR_EFFECT) is None
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_turn_on_default_spins(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Turning on with no effect spins, and the state follows the reply at once."""
    await _setup(hass, aioclient_mock, mock_config_entry)
    aioclient_mock.post(f"{BASE}/spin", json=status_json("spin"))

    await _light(hass, "turn_on")

    assert _posts(aioclient_mock) == [f"{BASE}/spin"]
    light = hass.states.get(ENTITY_ID)
    assert light.state == STATE_ON
    assert light.attributes[ATTR_EFFECT] == "spin"


async def test_turn_on_with_flash_effect(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The flash effect flashes."""
    await _setup(hass, aioclient_mock, mock_config_entry)
    aioclient_mock.post(f"{BASE}/flash", json=status_json("flash"))

    await _light(hass, "turn_on", effect="flash")

    assert _posts(aioclient_mock) == [f"{BASE}/flash"]
    assert hass.states.get(ENTITY_ID).attributes[ATTR_EFFECT] == "flash"


async def test_turn_on_while_flashing_keeps_flash(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Turning on a light that is already flashing keeps it flashing."""
    await _setup(hass, aioclient_mock, mock_config_entry, "flash")
    aioclient_mock.post(f"{BASE}/flash", json=status_json("flash"))

    await _light(hass, "turn_on")

    assert _posts(aioclient_mock) == [f"{BASE}/flash"]


async def test_turn_off_stops(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Turning off stops the beacon."""
    await _setup(hass, aioclient_mock, mock_config_entry, "spin")
    aioclient_mock.post(f"{BASE}/stop", json=status_json("idle"))

    await _light(hass, "turn_off")

    assert _posts(aioclient_mock) == [f"{BASE}/stop"]
    assert hass.states.get(ENTITY_ID).state == STATE_OFF


async def test_light_unavailable_when_unplugged(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """With no USB light, there is no light to control."""
    await _setup(hass, aioclient_mock, mock_config_entry, connected=False)

    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE


async def test_turn_on_503_raises(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A light unplugged since the last poll fails the call, naming the beacon."""
    await _setup(hass, aioclient_mock, mock_config_entry)
    aioclient_mock.post(
        f"{BASE}/spin", status=503, json={"error": "beacon disconnected"}
    )

    with pytest.raises(HomeAssistantError) as err:
        await _light(hass, "turn_on")

    assert err.value.translation_key == "not_plugged_in"
    assert err.value.translation_placeholders == {
        "name": "Home beacon",
        "address": "192.0.2.10:1337",
    }
    assert str(err.value) == (
        "The beacon light of Home beacon is not plugged into its PC (192.0.2.10:1337)"
    )
