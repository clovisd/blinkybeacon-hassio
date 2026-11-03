"""Fixtures for the BlinkyBeacon tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.blinkybeacon import usb_beacon
from custom_components.blinkybeacon.const import DOMAIN

from .fake_usb import FakeUsb

HOST = "192.0.2.10"
PORT = 1337
BASE = f"http://{HOST}:{PORT}"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from custom_components."""


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A config entry for the home team's beacon."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Home beacon",
        data={"host": HOST, "port": PORT},
        unique_id=f"{HOST}:{PORT}",
    )


def status_json(state: str = "idle", connected: bool = True) -> dict[str, Any]:
    """A reply as the tray sends it from /status and the control routes."""
    return {"state": state, "connected": connected}


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add the entry and set it up."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture(autouse=True)
def fake_usb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeUsb:
    """Point the USB code at a fake sysfs and /dev, empty until a test plugs in."""
    fake = FakeUsb(tmp_path / "usb")
    monkeypatch.setattr(usb_beacon, "SYSFS_ROOT", fake.sysfs)
    monkeypatch.setattr(usb_beacon, "DEV_ROOT", fake.dev)
    monkeypatch.setattr(usb_beacon, "_SKIPS_LOGGED", set())
    monkeypatch.setattr(usb_beacon, "_write_report", fake.write)
    return fake


@pytest.fixture
def usb_entry() -> MockConfigEntry:
    """A config entry for team A's beacon, on USB port 1-1."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Team A beacon",
        data={"usb_port": "1-1"},
        unique_id="usb:1-1",
    )
