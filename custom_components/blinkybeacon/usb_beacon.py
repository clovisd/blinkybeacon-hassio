"""Beacons plugged into this machine's USB ports, driven without a tray.

The beacon is a HID device that takes three fixed 10-byte output reports. It
falls idle unless its report is written again every few seconds, and a write
that fails is how an unplugged beacon shows.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime
import logging
import os
from pathlib import Path
import re
import threading

from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .api import BeaconStatus, BlinkyBeaconNotConnectedError
from .const import KEEPALIVE_INTERVAL, STATE_FLASH, STATE_IDLE, STATE_SPIN

_LOGGER = logging.getLogger(__name__)

SYSFS_ROOT = Path("/sys")
DEV_ROOT = Path("/dev")

BEACON_HID_ID = "0003:0000340D:00001710"

REPORTS: dict[str, bytes] = {
    STATE_SPIN: bytes.fromhex("00 FF 01 66 C8 FF AD 52 81 D6"),
    STATE_FLASH: bytes.fromhex("00 FF 07 FF 50 FF 1C 8E B0 B8"),
    STATE_IDLE: bytes.fromhex("00 FF 00 00 64 00 32 9E D7 0D"),
}

_USB_PORT = re.compile(r"\d+-\d+(?:\.\d+)*")

_write_report = os.write

_SKIPS_LOGGED: set[tuple[str, str]] = set()


def usb_unique_id(port: str) -> str:
    """The unique ID of the entry for the beacon in a USB port."""
    return f"usb:{port}"


def usb_port(sysfs_path: str) -> str | None:
    """The USB port in a device's sysfs path, or None if it is not on USB.

    The port is the last path part named as Linux names a USB device: the bus,
    a dash, then the port on each hub down to it (1-1, 1-3.2).
    """
    for part in reversed(Path(sysfs_path).parts):
        if _USB_PORT.fullmatch(part):
            return part
    return None


def find_beacons(
    sysfs_root: str | os.PathLike[str] | None = None,
    dev_root: str | os.PathLike[str] | None = None,
) -> dict[str, str]:
    """Map every USB port holding a beacon to its device file.

    An entry that cannot be read is skipped, and logged once. This reads files:
    run it in the executor.
    """
    sysfs = SYSFS_ROOT if sysfs_root is None else Path(sysfs_root)
    dev = DEV_ROOT if dev_root is None else Path(dev_root)
    hidraw = sysfs / "class" / "hidraw"
    try:
        nodes = sorted(os.listdir(hidraw))
    except OSError:
        return {}
    found: dict[str, str] = {}
    for node in nodes:
        device = hidraw / node / "device"
        try:
            uevent = (device / "uevent").read_text(errors="replace")
            path = os.path.realpath(device)
        except OSError as err:
            _log_skipped(node, err)
            continue
        if _hid_id(uevent) != BEACON_HID_ID:
            continue
        if (port := usb_port(path)) is not None:
            found.setdefault(port, str(dev / node))
    return found


def _log_skipped(node: str, err: OSError) -> None:
    """Log an unreadable sysfs entry once per node and error type."""
    if (key := (node, type(err).__name__)) not in _SKIPS_LOGGED:
        _SKIPS_LOGGED.add(key)
        _LOGGER.debug("Skipped %s in sysfs: it could not be read (%s)", *key)


def _hid_id(uevent: str) -> str | None:
    for line in uevent.splitlines():
        key, _, value = line.partition("=")
        if key == "HID_ID":
            return value.strip().upper()
    return None


class UsbBeacon:
    """The beacon in one USB port, answering the same calls as a tray client.

    Reports are written in the executor, one at a time. Once started, the
    current mode's report is written again every few seconds. A write that
    fails, or a port with no beacon, closes the device; the next command or
    keepalive opens it again once the port holds a beacon, which is then idle.
    """

    def __init__(self, hass: HomeAssistant, port: str) -> None:
        self._hass = hass
        self.port = port
        self._lock = asyncio.Lock()
        # The device is used by one thread at a time, even after a caller stops
        # waiting for a write that is still running.
        self._device_lock = threading.RLock()
        self._fd: int | None = None
        self._mode = STATE_IDLE
        self._closed = False
        self._last_error: str | None = None
        self._cancel_keepalive: CALLBACK_TYPE | None = None

    async def async_start(self) -> None:
        """Set the beacon idle, then keep writing its mode unless it was closed."""
        await self._async_write(STATE_IDLE)
        if not self._closed:
            self._cancel_keepalive = async_track_time_interval(
                self._hass,
                self._async_keepalive,
                KEEPALIVE_INTERVAL,
                name=f"BlinkyBeacon USB port {self.port}",
                cancel_on_shutdown=True,
            )

    async def async_close(self) -> None:
        """Stop the keepalive, stop the beacon if it is there, and close it."""
        async with self._lock:
            self._closed = True
            if self._cancel_keepalive is not None:
                self._cancel_keepalive()
                self._cancel_keepalive = None
            await self._hass.async_add_executor_job(self._stop_and_close)
            self._mode = STATE_IDLE

    async def status(self) -> BeaconStatus:
        """The mode, and whether the beacon is in its port and took its last report."""
        async with self._lock:
            beacons = await self._hass.async_add_executor_job(find_beacons)
            if self.port not in beacons:
                await self._hass.async_add_executor_job(self._close)
                self._mode = STATE_IDLE
            return BeaconStatus(self._mode, self._fd is not None)

    async def spin(self) -> BeaconStatus:
        """Start spinning."""
        return await self._async_command(STATE_SPIN)

    async def flash(self) -> BeaconStatus:
        """Start flashing."""
        return await self._async_command(STATE_FLASH)

    async def stop(self) -> BeaconStatus:
        """Stop the light."""
        return await self._async_command(STATE_IDLE)

    async def _async_command(self, mode: str) -> BeaconStatus:
        if not await self._async_write(mode):
            raise BlinkyBeaconNotConnectedError
        return BeaconStatus(mode, True)

    async def _async_keepalive(self, _now: datetime) -> None:
        await self._async_write()

    async def _async_write(self, mode: str | None = None) -> bool:
        """Write a mode's report, or the current mode's; False if not taken.

        A write that fails and finds the beacon still in its port, or plugged
        straight back into it, writes the same report again: one failed
        keepalive does not stop a beacon that is on.
        """
        async with self._lock:
            if self._closed:
                return False
            if mode is None:
                mode = self._mode
            taken = await self._hass.async_add_executor_job(self._write, mode)
            if taken is not None:
                self._mode = taken
                return True
            self._mode = STATE_IDLE
            return False

    def _write(self, mode: str) -> str | None:
        """Write a mode's report; return the mode the beacon took, or None.

        A device left open by an earlier write is gone once its beacon is
        unplugged, even if the port holds a beacon again. A write through it
        that fails closes it and, if the port still holds a beacon, writes the
        same report once to the device opened again.
        """
        with self._device_lock:
            if self._closed:
                return None
            first_error: str | None = None
            if self._fd is not None:
                try:
                    written = _write_report(self._fd, REPORTS[mode])
                except OSError as err:
                    first_error = type(err).__name__
                    self._close()
                else:
                    return self._taken(mode, written)
            try:
                if (path := find_beacons().get(self.port)) is None:
                    if first_error is not None:
                        self._failed(first_error)
                    return None
                self._fd = os.open(path, os.O_WRONLY | os.O_CLOEXEC)
                written = _write_report(self._fd, REPORTS[mode])
            except OSError as err:
                self._failed(type(err).__name__)
                return None
            if first_error is not None:
                _LOGGER.warning(
                    "The beacon on USB port %s was opened again after a write"
                    " failed (%s)",
                    self.port,
                    first_error,
                )
            return self._taken(mode, written)

    def _taken(self, mode: str, written: int) -> str | None:
        """The mode, if its report was written whole."""
        if written != len(REPORTS[mode]):
            self._failed("short write")
            return None
        self._last_error = None
        return mode

    def _stop_and_close(self) -> None:
        with self._device_lock:
            if self._fd is not None:
                report = REPORTS[STATE_IDLE]
                try:
                    written = _write_report(self._fd, report)
                except OSError as err:
                    self._failed(type(err).__name__)
                else:
                    if written != len(report):
                        self._failed("short write")
            self._close()

    def _failed(self, kind: str) -> None:
        self._close()
        if kind != self._last_error:
            self._last_error = kind
            _LOGGER.warning(
                "The beacon on USB port %s did not take a report (%s)", self.port, kind
            )

    def _close(self) -> None:
        with self._device_lock:
            if self._fd is not None:
                with suppress(OSError):
                    os.close(self._fd)
                self._fd = None
