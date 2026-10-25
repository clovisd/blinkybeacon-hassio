"""Tests for the USB connected sensor."""

from __future__ import annotations

import aiohttp
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.blinkybeacon.const import SCAN_INTERVAL

from .conftest import BASE, setup_integration, status_json

ENTITY_ID = "binary_sensor.home_beacon_usb_connected"


async def _next_poll(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    **reply: object,
) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/status", **reply)
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_usb_connected_on_off(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The sensor follows the tray's connected flag at each poll."""
    aioclient_mock.get(f"{BASE}/status", json=status_json())
    await setup_integration(hass, mock_config_entry)
    assert hass.states.get(ENTITY_ID).state == STATE_ON

    await _next_poll(
        hass, aioclient_mock, freezer, json=status_json(connected=False)
    )

    assert hass.states.get(ENTITY_ID).state == STATE_OFF


async def test_usb_sensor_unavailable_when_tray_unreachable(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A tray that stops answering makes the sensor unavailable until it is back."""
    aioclient_mock.get(f"{BASE}/status", json=status_json())
    await setup_integration(hass, mock_config_entry)

    await _next_poll(hass, aioclient_mock, freezer, exc=aiohttp.ClientError())
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE

    await _next_poll(hass, aioclient_mock, freezer, json=status_json())
    assert hass.states.get(ENTITY_ID).state == STATE_ON
