"""Tests for driving a beacon in a USB port."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
import errno
import logging
import threading

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest

from custom_components.blinkybeacon import usb_beacon
from custom_components.blinkybeacon.api import (
    BeaconStatus,
    BlinkyBeaconNotConnectedError,
)
from custom_components.blinkybeacon.usb_beacon import UsbBeacon

from .fake_usb import FLASH, SPIN, STOP, FakeUsb, tick


@pytest.fixture
async def beacon(hass: HomeAssistant) -> AsyncGenerator[UsbBeacon]:
    """The driver for USB port 1-1, closed after the test."""
    beacon = UsbBeacon(hass, "1-1")
    yield beacon
    await beacon.async_close()


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == usb_beacon.__name__ and r.levelno == logging.WARNING
    ]


async def test_start_sets_idle(fake_usb: FakeUsb, beacon: UsbBeacon) -> None:
    """Starting writes stop, so the beacon is idle and known to be there."""
    fake_usb.plug("1-1")

    await beacon.async_start()

    assert fake_usb.written() == [STOP]
    assert await beacon.status() == BeaconStatus("idle", True)


async def test_commands_write_their_report(
    fake_usb: FakeUsb, beacon: UsbBeacon
) -> None:
    """Spin, flash and stop each write their report and answer the new state."""
    fake_usb.plug("1-1")
    await beacon.async_start()

    assert await beacon.spin() == BeaconStatus("spin", True)
    assert await beacon.flash() == BeaconStatus("flash", True)
    assert await beacon.stop() == BeaconStatus("idle", True)

    assert fake_usb.written() == [STOP, SPIN, FLASH, STOP]


async def test_keepalive_repeats_the_mode(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    beacon: UsbBeacon,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The current mode's report is written again every 5 seconds, not sooner."""
    fake_usb.plug("1-1")
    await beacon.async_start()
    await beacon.spin()

    await tick(hass, freezer, 4)
    assert fake_usb.written() == [STOP, SPIN]

    await tick(hass, freezer, 1)
    assert fake_usb.written() == [STOP, SPIN, SPIN]

    await beacon.flash()
    await tick(hass, freezer, 5)
    assert fake_usb.written() == [STOP, SPIN, SPIN, FLASH, FLASH]


async def test_missing_at_start_then_plugged_in(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    beacon: UsbBeacon,
    freezer: FrozenDateTimeFactory,
) -> None:
    """An empty port is not connected; once plugged in, the keepalive finds it."""
    await beacon.async_start()

    assert await beacon.status() == BeaconStatus("idle", False)
    with pytest.raises(BlinkyBeaconNotConnectedError):
        await beacon.spin()

    fake_usb.plug("1-1")
    await tick(hass, freezer, 5)

    assert fake_usb.written() == [STOP]
    assert await beacon.status() == BeaconStatus("idle", True)
    assert await beacon.spin() == BeaconStatus("spin", True)


async def test_failed_write_until_back(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    beacon: UsbBeacon,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A write that fails is not connected; once writes work again it is back, idle."""
    fake_usb.plug("1-1")
    await beacon.async_start()
    await beacon.spin()

    fake_usb.write_error = OSError(errno.ENODEV, "No such device")
    await tick(hass, freezer, 5)

    assert await beacon.status() == BeaconStatus("idle", False)
    assert _warnings(caplog) == [
        "The beacon on USB port 1-1 did not take a report (OSError)"
    ]

    fake_usb.write_error = None
    await tick(hass, freezer, 5)

    assert await beacon.status() == BeaconStatus("idle", True)
    assert fake_usb.written() == [STOP, SPIN, STOP]


async def test_one_failed_keepalive_write_leaves_the_beacon_in_its_mode(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    beacon: UsbBeacon,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A keepalive write that fails once opens the beacon again and writes its mode."""
    fake_usb.plug("1-1")
    await beacon.async_start()
    await beacon.spin()

    fake_usb.write_error_once = OSError(errno.EIO, "Input/output error")
    await tick(hass, freezer, 5)

    assert fake_usb.written() == [STOP, SPIN, SPIN]
    assert await beacon.status() == BeaconStatus("spin", True)
    assert _warnings(caplog) == [
        "The beacon on USB port 1-1 was opened again after a write failed (OSError)"
    ]

    await tick(hass, freezer, 5)
    assert fake_usb.written() == [STOP, SPIN, SPIN, SPIN]


async def test_unplug_and_replug_on_another_node(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    beacon: UsbBeacon,
    freezer: FrozenDateTimeFactory,
) -> None:
    """An empty port is not connected; the beacon is found again by its port."""
    fake_usb.plug("1-1", "hidraw0")
    await beacon.async_start()
    await beacon.spin()

    fake_usb.unplug("hidraw0")
    assert await beacon.status() == BeaconStatus("idle", False)

    fake_usb.plug("1-1", "hidraw3")
    await tick(hass, freezer, 5)

    assert await beacon.status() == BeaconStatus("idle", True)
    await beacon.flash()
    assert fake_usb.written("hidraw3") == [STOP, FLASH]


async def test_command_right_after_a_quick_replug(
    fake_usb: FakeUsb, beacon: UsbBeacon, caplog: pytest.LogCaptureFixture
) -> None:
    """A beacon plugged straight back into its port takes the next command."""
    fake_usb.plug("1-1")
    await beacon.async_start()

    fake_usb.unplug()
    fake_usb.plug("1-1")

    assert await beacon.spin() == BeaconStatus("spin", True)
    assert fake_usb.written() == [SPIN]
    assert await beacon.status() == BeaconStatus("spin", True)
    assert _warnings(caplog) == [
        "The beacon on USB port 1-1 was opened again after a write failed (OSError)"
    ]


async def test_keepalive_after_a_quick_replug_writes_its_mode_again(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    beacon: UsbBeacon,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A keepalive that finds the beacon plugged straight back in keeps its mode."""
    fake_usb.plug("1-1")
    await beacon.async_start()
    await beacon.spin()

    fake_usb.unplug()
    fake_usb.plug("1-1")
    await tick(hass, freezer, 5)

    assert fake_usb.written() == [SPIN]
    assert await beacon.status() == BeaconStatus("spin", True)
    assert _warnings(caplog) == [
        "The beacon on USB port 1-1 was opened again after a write failed (OSError)"
    ]

    await tick(hass, freezer, 5)
    assert fake_usb.written() == [SPIN, SPIN]


async def test_open_error_logged_once_without_system_text(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    beacon: UsbBeacon,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A device that cannot be opened is logged once, by error type and port."""
    device = fake_usb.plug("1-1")
    device.unlink()
    device.mkdir()

    await beacon.async_start()
    await tick(hass, freezer, 5)
    await tick(hass, freezer, 5)

    assert await beacon.status() == BeaconStatus("idle", False)
    assert _warnings(caplog) == [
        "The beacon on USB port 1-1 did not take a report (IsADirectoryError)"
    ]
    assert "Is a directory" not in caplog.text


async def test_short_write_is_not_connected(
    fake_usb: FakeUsb, beacon: UsbBeacon, caplog: pytest.LogCaptureFixture
) -> None:
    """A report the device did not take whole counts as not taken."""
    fake_usb.plug("1-1")
    fake_usb.short_writes = True

    await beacon.async_start()

    assert await beacon.status() == BeaconStatus("idle", False)
    assert _warnings(caplog) == [
        "The beacon on USB port 1-1 did not take a report (short write)"
    ]


async def test_close_stops_the_beacon_and_the_keepalive(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    beacon: UsbBeacon,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Closing writes stop once, ends the keepalive, and refuses later commands."""
    fake_usb.plug("1-1")
    await beacon.async_start()
    await beacon.spin()

    await beacon.async_close()
    await tick(hass, freezer, 10)

    assert fake_usb.written() == [STOP, SPIN, STOP]
    assert await beacon.status() == BeaconStatus("idle", False)
    with pytest.raises(BlinkyBeaconNotConnectedError):
        await beacon.spin()


async def test_close_when_not_connected_writes_nothing(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    beacon: UsbBeacon,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A beacon that is not connected is not opened again just to stop it."""
    fake_usb.plug("1-1")
    await beacon.async_start()
    fake_usb.write_error = OSError(errno.EIO, "Input/output error")
    await tick(hass, freezer, 5)
    fake_usb.write_error = None

    await beacon.async_close()

    assert fake_usb.written() == [STOP]


async def test_keepalive_never_writes_an_older_mode(
    fake_usb: FakeUsb, beacon: UsbBeacon
) -> None:
    """A keepalive queued behind a command writes the new mode, not the old."""
    fake_usb.plug("1-1")
    await beacon.async_start()

    async with beacon._lock:
        spin = asyncio.ensure_future(beacon.spin())
        await asyncio.sleep(0)
        keepalive = asyncio.ensure_future(beacon._async_keepalive(dt_util.utcnow()))
        await asyncio.sleep(0)
    await asyncio.gather(spin, keepalive)

    assert fake_usb.written() == [STOP, SPIN, SPIN]
    assert await beacon.status() == BeaconStatus("spin", True)


async def test_keepalive_queued_behind_close_does_not_reopen(
    fake_usb: FakeUsb, beacon: UsbBeacon
) -> None:
    """A keepalive already queued when the beacon closes writes nothing."""
    fake_usb.plug("1-1")
    await beacon.async_start()

    async with beacon._lock:
        close = asyncio.ensure_future(beacon.async_close())
        await asyncio.sleep(0)
        keepalive = asyncio.ensure_future(beacon._async_keepalive(dt_util.utcnow()))
        await asyncio.sleep(0)
    await asyncio.gather(close, keepalive)

    assert fake_usb.written() == [STOP, STOP]
    assert await beacon.status() == BeaconStatus("idle", False)


async def test_write_left_running_past_close_does_not_reopen(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    beacon: UsbBeacon,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A write its caller stopped waiting for, run after the close, opens nothing."""
    fake_usb.plug("1-1")
    await beacon.async_start()
    started = threading.Event()
    release = threading.Event()
    done = threading.Event()
    write = beacon._write

    def held_write(*args: object) -> object:
        started.set()
        release.wait(5)
        try:
            return write(*args)
        finally:
            done.set()

    monkeypatch.setattr(beacon, "_write", held_write)

    cancelled = asyncio.ensure_future(beacon.spin())
    assert await hass.async_add_executor_job(started.wait, 5)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    await beacon.async_close()
    release.set()
    assert await hass.async_add_executor_job(done.wait, 5)

    assert fake_usb.written() == [STOP, STOP]
    assert beacon._fd is None


@pytest.mark.parametrize(
    ("first", "then", "writes"),
    [
        ("async_start", "async_close", [STOP, STOP]),
        ("async_close", "async_start", []),
    ],
    ids=["start_then_close", "close_then_start"],
)
async def test_close_queued_with_start_leaves_no_keepalive(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    beacon: UsbBeacon,
    freezer: FrozenDateTimeFactory,
    first: str,
    then: str,
    writes: list[bytes],
) -> None:
    """A start and a close queued together, either way round, leave no keepalive."""
    fake_usb.plug("1-1")

    async with beacon._lock:
        one = asyncio.ensure_future(getattr(beacon, first)())
        await asyncio.sleep(0)
        two = asyncio.ensure_future(getattr(beacon, then)())
        await asyncio.sleep(0)
    await asyncio.gather(one, two)

    assert beacon._cancel_keepalive is None
    assert fake_usb.written() == writes
    await tick(hass, freezer, 10)
    assert fake_usb.written() == writes


async def test_device_used_by_one_thread_at_a_time(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    beacon: UsbBeacon,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A write its caller stopped waiting for ends before the next write begins."""
    fake_usb.plug("1-1")
    events: list[str] = []
    inside = 0
    most_inside = 0
    count_lock = threading.Lock()
    first_inside = threading.Event()
    second_inside = threading.Event()
    release = threading.Event()

    def blocking_write(fd: int, report: bytes) -> int:
        nonlocal inside, most_inside
        with count_lock:
            first = not first_inside.is_set()
            name = "first" if first else "second"
            inside += 1
            most_inside = max(most_inside, inside)
            events.append(f"{name} in")
        (first_inside if first else second_inside).set()
        if first:
            release.wait(5)
        try:
            return fake_usb.write(fd, report)
        finally:
            with count_lock:
                inside -= 1
                events.append(f"{name} out")

    monkeypatch.setattr(usb_beacon, "_write_report", blocking_write)

    cancelled = asyncio.ensure_future(beacon.spin())
    assert await hass.async_add_executor_job(first_inside.wait, 5)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled

    second = asyncio.ensure_future(beacon.spin())
    await hass.async_add_executor_job(second_inside.wait, 0.5)
    release.set()

    assert await asyncio.wait_for(second, 10) == BeaconStatus("spin", True)
    assert most_inside == 1
    assert events == ["first in", "first out", "second in", "second out"]
    assert fake_usb.written() == [SPIN, SPIN]


async def test_close_logs_a_stop_not_taken_whole(
    fake_usb: FakeUsb, beacon: UsbBeacon, caplog: pytest.LogCaptureFixture
) -> None:
    """A final stop the device did not take whole is logged, once."""
    fake_usb.plug("1-1")
    await beacon.async_start()
    fake_usb.short_writes = True

    await beacon.async_close()

    assert _warnings(caplog) == [
        "The beacon on USB port 1-1 did not take a report (short write)"
    ]
