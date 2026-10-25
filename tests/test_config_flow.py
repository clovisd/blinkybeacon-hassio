"""Tests for adding and reconfiguring a beacon."""

from __future__ import annotations

import aiohttp
import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.blinkybeacon.config_flow import normalize_host
from custom_components.blinkybeacon.const import DOMAIN

from .conftest import BASE, HOST, PORT, status_json

USER_INPUT = {"host": HOST, "port": PORT, "name": "Home beacon"}


async def _start(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return result["flow_id"]


async def test_user_flow_creates_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A tray that answers /status becomes an entry named as typed."""
    aioclient_mock.get(f"{BASE}/status", json=status_json())

    result = await hass.config_entries.flow.async_configure(
        await _start(hass), USER_INPUT
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home beacon"
    assert result["data"] == {"host": HOST, "port": PORT}
    assert result["result"].unique_id == "192.0.2.10:1337"


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A tray that does not answer keeps the form open with an error."""
    aioclient_mock.get(f"{BASE}/status", exc=aiohttp.ClientError())
    flow_id = await _start(hass)

    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/status", json=status_json())
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_invalid_reply(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Something that is not a tray on that port is named as such."""
    aioclient_mock.get(f"{BASE}/status", text="<html>router</html>")

    result = await hass.config_entries.flow.async_configure(
        await _start(hass), USER_INPUT
    )

    assert result["errors"] == {"base": "invalid_reply"}


async def test_user_flow_url_typed_as_host(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A URL pasted into the host field is reduced to host and port."""
    aioclient_mock.get(f"http://{HOST}:1338/status", json=status_json())

    result = await hass.config_entries.flow.async_configure(
        await _start(hass), {**USER_INPUT, "host": f"http://{HOST}:1338/"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"host": HOST, "port": 1338}


async def test_user_flow_invalid_host(hass: HomeAssistant) -> None:
    """A host with a path in it is refused before anything is called."""
    result = await hass.config_entries.flow.async_configure(
        await _start(hass), {**USER_INPUT, "host": f"{HOST}/settings"}
    )

    assert result["errors"] == {"host": "invalid_host"}


async def test_user_flow_port_out_of_range(hass: HomeAssistant) -> None:
    """The form's schema refuses a port above 65535."""
    flow_id = await _start(hass)

    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            flow_id, {**USER_INPUT, "port": 70000}
        )


async def test_user_flow_already_configured(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The same host:port cannot be added twice."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(f"{BASE}/status", json=status_json())

    result = await hass.config_entries.flow.async_configure(
        await _start(hass), USER_INPUT
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_updates_address(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Reconfigure moves the entry to the tray's new address."""
    aioclient_mock.get(f"{BASE}/status", json=status_json())
    aioclient_mock.get("http://192.0.2.11:1337/status", json=status_json())
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "192.0.2.11", "port": PORT}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data["host"] == "192.0.2.11"
    assert mock_config_entry.unique_id == "192.0.2.11:1337"


async def test_reconfigure_to_existing_address_aborts(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Reconfigure cannot point one beacon at another beacon's tray."""
    mock_config_entry.add_to_hass(hass)
    MockConfigEntry(
        domain=DOMAIN,
        title="Away beacon",
        data={"host": "192.0.2.11", "port": PORT},
        unique_id="192.0.2.11:1337",
    ).add_to_hass(hass)
    aioclient_mock.get("http://192.0.2.11:1337/status", json=status_json())

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "192.0.2.11", "port": PORT}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("192.0.2.10", ("192.0.2.10", 1337)),
        ("  beacon-pc.local  ", ("beacon-pc.local", 1337)),
        ("192.0.2.10:1338", ("192.0.2.10", 1338)),
        ("HTTPS://192.0.2.10/", ("192.0.2.10", 1337)),
        ("fd00::5", ("fd00::5", 1337)),
        ("[fd00::5]", ("fd00::5", 1337)),
        ("http://[fd00::5]:1338/", ("fd00::5", 1338)),
    ],
)
def test_normalize_host_accepts(raw: str, expected: tuple[str, int]) -> None:
    """Hosts, host:port, IPv6 and URLs reduce to host and port."""
    assert normalize_host(raw, 1337) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "http://", "192.0.2.10/settings", "192.0.2.10:0", "192.0.2.10:99999",
     "192.0.2.10:abc", "[fd00::5", "[fd00::5]x", "[]:1337"],
)
def test_normalize_host_refuses(raw: str) -> None:
    """Anything with a path, a bad port or a broken IPv6 literal is refused."""
    with pytest.raises(ValueError):
        normalize_host(raw, 1337)
