"""A fake sysfs and /dev in a temporary directory, laid out as Linux lists them."""

from __future__ import annotations

from datetime import timedelta
import errno
import os
from pathlib import Path
import shutil

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_fire_time_changed

BEACON_HID_ID = "0003:0000340D:00001710"
KEYBOARD_HID_ID = "0003:0000046D:0000C31C"

SPIN = bytes.fromhex("00 FF 01 66 C8 FF AD 52 81 D6")
FLASH = bytes.fromhex("00 FF 07 FF 50 FF 1C 8E B0 B8")
STOP = bytes.fromhex("00 FF 00 00 64 00 32 9E D7 0D")


async def tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float
) -> None:
    """Move the clock on and wait for what it set off, keepalives and scans included."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


class FakeUsb:
    """USB ports to plug fake HID devices into, and the reports written to them."""

    def __init__(self, root: Path) -> None:
        self.sysfs = root / "sys"
        self.dev = root / "dev"
        (self.sysfs / "class" / "hidraw").mkdir(parents=True)
        self.dev.mkdir()
        self.write_error: OSError | None = None
        self.short_writes = False
        self._devices = 0

    def plug(
        self,
        port: str,
        node: str = "hidraw0",
        hid_id: str = BEACON_HID_ID,
        controller: str = "pci0000:00/0000:00:14.0",
    ) -> Path:
        """Plug a HID device into a port; return its device file.

        A hub port such as 1-3.2 sits under its hub's port 1-3, as in sysfs.
        """
        self._devices += 1
        bus, _, chain = port.partition("-")
        hops = chain.split(".")
        ports = [f"{bus}-{'.'.join(hops[: i + 1])}" for i in range(len(hops))]
        _, vendor, product = hid_id.split(":")
        device = Path(
            self.sysfs,
            "devices",
            controller,
            f"usb{bus}",
            *ports,
            f"{port}:1.0",
            f"0003:{vendor[-4:]}:{product[-4:]}.{self._devices:04X}",
        )
        device.mkdir(parents=True)
        (device / "uevent").write_text(
            "DRIVER=hid-generic\n"
            f"HID_ID={hid_id}\n"
            "HID_NAME=Beacon Light Orange\n"
            f"HID_PHYS=usb-0000:00:14.0-{port}/input0\n"
            "HID_UNIQ=\n"
            f"MODALIAS=hid:b0003g0001v{vendor}p{product}\n"
        )
        entry = self.sysfs / "class" / "hidraw" / node
        entry.mkdir()
        (entry / "device").symlink_to(device)
        device_file = self.dev / node
        device_file.write_bytes(b"")
        return device_file

    def unplug(self, node: str = "hidraw0") -> None:
        """Take a device away: its sysfs entry and its device file."""
        shutil.rmtree(self.sysfs / "class" / "hidraw" / node)
        (self.dev / node).unlink()

    def written(self, node: str = "hidraw0") -> list[bytes]:
        """The reports written to a device file, in order."""
        data = (self.dev / node).read_bytes()
        return [data[i : i + 10] for i in range(0, len(data), 10)]

    def write(self, fd: int, report: bytes) -> int:
        """Stands in for os.write: fails while write_error is set.

        A descriptor whose device was taken away fails as Linux fails it, with
        ENODEV, even once a new device is plugged into the same port. A device
        has no position, so each report goes after the ones before it, even
        through a newly opened descriptor.
        """
        if os.fstat(fd).st_nlink == 0:
            raise OSError(errno.ENODEV, "No such device")
        if self.write_error is not None:
            raise self.write_error
        os.lseek(fd, 0, os.SEEK_END)
        if self.short_writes:
            return os.write(fd, report[:5])
        return os.write(fd, report)
