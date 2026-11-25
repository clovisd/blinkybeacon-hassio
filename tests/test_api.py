"""Tests for the tray API client."""

from __future__ import annotations

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.blinkybeacon.api import (
    BeaconStatus,
    BlinkyBeaconClient,
    BlinkyBeaconConnectionError,
    BlinkyBeaconNotConnectedError,
    BlinkyBeaconResponseError,
)
from custom_components.blinkybeacon.const import MAX_REPLY, MAX_SHOWN

from .conftest import BASE, HOST, PORT, status_json


def _client(hass: HomeAssistant, host: str = HOST) -> BlinkyBeaconClient:
    return BlinkyBeaconClient(async_get_clientsession(hass), host, PORT)


async def test_status_parses_reply(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """GET /status becomes a BeaconStatus."""
    aioclient_mock.get(f"{BASE}/status", json=status_json("spin", True))

    assert await _client(hass).status() == BeaconStatus("spin", True)


@pytest.mark.parametrize(
    ("command", "state"), [("spin", "spin"), ("flash", "flash"), ("stop", "idle")]
)
async def test_commands_post_and_parse(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    command: str,
    state: str,
) -> None:
    """Each command is a POST to its route, and its reply is parsed."""
    aioclient_mock.post(f"{BASE}/{command}", json=status_json(state))

    result = await getattr(_client(hass), command)()

    assert result == BeaconStatus(state, True)
    assert aioclient_mock.mock_calls[0][0] == "POST"


async def test_503_raises_not_connected(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 503 means the tray is up but its USB light is not."""
    aioclient_mock.post(
        f"{BASE}/spin", status=503, json={"error": "beacon not connected"}
    )

    with pytest.raises(BlinkyBeaconNotConnectedError):
        await _client(hass).spin()


@pytest.mark.parametrize("exc", [aiohttp.ClientError(), TimeoutError()])
async def test_unreachable_raises_connection_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, exc: Exception
) -> None:
    """A tray that does not answer is a connection error."""
    aioclient_mock.get(f"{BASE}/status", exc=exc)

    with pytest.raises(BlinkyBeaconConnectionError):
        await _client(hass).status()


async def test_html_reply_raises_response_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Something other than the tray answering on that port is not a crash."""
    aioclient_mock.get(f"{BASE}/status", text="<html>router</html>")

    with pytest.raises(BlinkyBeaconResponseError):
        await _client(hass).status()


async def test_wrong_shape_raises_response_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """JSON without a string state and a bool connected is refused."""
    aioclient_mock.get(f"{BASE}/status", json={"state": 3})

    with pytest.raises(BlinkyBeaconResponseError):
        await _client(hass).status()


async def test_reply_over_the_limit_is_refused_without_being_kept(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A reply far longer than the tray's is refused, and none of it is shown."""
    aioclient_mock.get(f"{BASE}/status", json={**status_json(), "pad": "x" * 1_000_000})

    with pytest.raises(BlinkyBeaconResponseError) as caught:
        await _client(hass).status()

    assert str(caught.value) == f"GET /status answered more than {MAX_REPLY} bytes"


async def test_reply_at_the_limit_is_read(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A reply of exactly the limit is still the tray's to give."""
    reply = b'{"state":"idle","connected":true}'
    aioclient_mock.get(f"{BASE}/status", content=reply.ljust(MAX_REPLY))

    assert await _client(hass).status() == BeaconStatus("idle", True)


async def test_wrong_shape_is_shown_cut_short(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """What a wrong reply held is shown up to a few characters, not whole."""
    aioclient_mock.get(f"{BASE}/status", json={"state": 3, "pad": "x" * 800})

    with pytest.raises(BlinkyBeaconResponseError) as caught:
        await _client(hass).status()

    message = str(caught.value)
    assert message.startswith("GET /status answered {'state': 3, 'pad': 'xxx")
    assert message.endswith("…")
    assert len(message) == len("GET /status answered ") + MAX_SHOWN + 1


async def test_other_status_raises_response_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Any status other than 200 or 503 is an unexpected reply."""
    aioclient_mock.post(f"{BASE}/stop", status=500, text="boom")

    with pytest.raises(BlinkyBeaconResponseError):
        await _client(hass).stop()


async def test_ipv6_base_url(hass: HomeAssistant) -> None:
    """An IPv6 literal is bracketed in the URL."""
    assert _client(hass, "fd00::5").base_url == "http://[fd00::5]:1337"
