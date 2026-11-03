"""Tests for finding beacons in USB ports, and the reports they take."""

from __future__ import annotations

import logging
import os

import pytest

from custom_components.blinkybeacon import usb_beacon
from custom_components.blinkybeacon.usb_beacon import (
    REPORTS,
    find_beacons,
    usb_port,
    usb_unique_id,
)

from .fake_usb import FLASH, KEYBOARD_HID_ID, SPIN, STOP, FakeUsb


def test_reports_are_the_beacon_protocol() -> None:
    """Each mode is one fixed 10-byte output report, report ID 0 first."""
    assert REPORTS == {"spin": SPIN, "flash": FLASH, "idle": STOP}
    assert REPORTS["spin"].hex(" ") == "00 ff 01 66 c8 ff ad 52 81 d6"
    assert REPORTS["flash"].hex(" ") == "00 ff 07 ff 50 ff 1c 8e b0 b8"
    assert REPORTS["idle"].hex(" ") == "00 ff 00 00 64 00 32 9e d7 0d"


@pytest.mark.parametrize(
    ("path", "port"),
    [
        (
            "/sys/devices/pci0000:00/0000:00:14.0/usb1/1-1/1-1:1.0/0003:340D:1710.0004",
            "1-1",
        ),
        (
            "/sys/devices/pci0000:00/0000:00:14.0/usb1/1-3/1-3.2/1-3.2:1.0/"
            "0003:340D:1710.0007",
            "1-3.2",
        ),
        (
            "/sys/devices/platform/xhci-hcd.0/usb2/2-1/2-1:1.0/0003:340D:1710.0001",
            "2-1",
        ),
        ("/sys/devices/virtual/misc/uhid/0003:340D:1710.0002", None),
        ("/tmp/pytest-of-ha/pytest-12/sys/devices/virtual/misc/uhid/0003:X", None),
    ],
)
def test_usb_port_from_sysfs_path(path: str, port: str | None) -> None:
    """The port is the last path part named like a USB device, or None off USB."""
    assert usb_port(path) == port


def test_unique_id() -> None:
    """A USB beacon's entry is known by its port."""
    assert usb_unique_id("1-3.2") == "usb:1-3.2"


def test_find_direct_port(fake_usb: FakeUsb) -> None:
    """A beacon in a port of the machine maps that port to its device file."""
    fake_usb.plug("1-1")

    assert find_beacons(fake_usb.sysfs, fake_usb.dev) == {
        "1-1": str(fake_usb.dev / "hidraw0")
    }


def test_find_hub_ports(fake_usb: FakeUsb) -> None:
    """Beacons behind a hub are known by their hub port; others are skipped."""
    fake_usb.plug("1-3.1", "hidraw0")
    fake_usb.plug("1-3.2", "hidraw2")
    fake_usb.plug("1-4", "hidraw1", hid_id=KEYBOARD_HID_ID)

    assert find_beacons(fake_usb.sysfs, fake_usb.dev) == {
        "1-3.1": str(fake_usb.dev / "hidraw0"),
        "1-3.2": str(fake_usb.dev / "hidraw2"),
    }


def test_find_defaults_to_the_module_roots(fake_usb: FakeUsb) -> None:
    """With no arguments it reads the module's sysfs and /dev roots."""
    fake_usb.plug("1-2")

    assert find_beacons() == {"1-2": str(fake_usb.dev / "hidraw0")}


def test_find_hid_id_case_and_spacing(fake_usb: FakeUsb) -> None:
    """The HID ID is matched whatever its case, with trailing spaces dropped."""
    fake_usb.plug("1-1")
    uevent = next(fake_usb.sysfs.glob("devices/**/uevent"))
    uevent.write_text(
        uevent.read_text().replace(
            "HID_ID=0003:0000340D:00001710\n", "HID_ID=0003:0000340d:00001710 \n"
        )
    )

    assert list(find_beacons()) == ["1-1"]


@pytest.mark.parametrize(
    "damage",
    ["uevent_is_a_directory", "dangling_device_link", "no_hid_id", "not_text"],
)
def test_find_skips_what_it_cannot_read(fake_usb: FakeUsb, damage: str) -> None:
    """A device whose files cannot be read is skipped; the others are still found."""
    fake_usb.plug("1-1", "hidraw0")
    fake_usb.plug("1-2", "hidraw1")
    device = (fake_usb.sysfs / "class" / "hidraw" / "hidraw0" / "device").resolve()
    if damage == "uevent_is_a_directory":
        (device / "uevent").unlink()
        (device / "uevent").mkdir()
    elif damage == "dangling_device_link":
        link = fake_usb.sysfs / "class" / "hidraw" / "hidraw0" / "device"
        link.unlink()
        link.symlink_to(fake_usb.sysfs / "devices" / "gone")
    elif damage == "no_hid_id":
        (device / "uevent").write_text("DRIVER=hid-generic\nHID_NAME=Beacon\n")
    else:
        (device / "uevent").write_bytes(b"HID_ID=\xff\xfe\x00\n")

    assert find_beacons() == {"1-2": str(fake_usb.dev / "hidraw1")}


def test_find_without_hidraw_class(fake_usb: FakeUsb) -> None:
    """A machine with no HID devices at all has no beacons, and no error."""
    (fake_usb.sysfs / "class" / "hidraw").rmdir()

    assert find_beacons() == {}


def test_find_off_usb_is_skipped(fake_usb: FakeUsb) -> None:
    """A beacon-like device that is not on a USB port has no port to be known by."""
    fake_usb.plug("1-1")
    link = fake_usb.sysfs / "class" / "hidraw" / "hidraw0" / "device"
    virtual = fake_usb.sysfs / "devices" / "virtual" / "misc" / "uhid" / "0003:X"
    virtual.mkdir(parents=True)
    (virtual / "uevent").write_text((link.resolve() / "uevent").read_text())
    link.unlink()
    link.symlink_to(virtual)

    assert find_beacons() == {}


def test_find_takes_roots_as_strings(fake_usb: FakeUsb) -> None:
    """The roots may be given as strings as well as paths."""
    fake_usb.plug("1-1")

    assert find_beacons(str(fake_usb.sysfs), str(fake_usb.dev)) == {
        "1-1": str(fake_usb.dev / "hidraw0")
    }


def test_find_on_the_measured_layout(fake_usb: FakeUsb) -> None:
    """Laid out as a real machine lists it, only the beacon on 1-1 is found.

    Each class entry is a relative link into the device tree, and the device's
    own hidraw directory links back to it; three HID interfaces of another
    device sit on port 1-3.
    """
    usb1 = fake_usb.sysfs / "devices" / "pci0000:00" / "0000:00:14.0" / "usb1"
    devices = [
        ("hidraw0", "1-3", "1-3:1.0", "0003:38EB:0001.0001", "0003:000038EB:00000001"),
        ("hidraw1", "1-3", "1-3:1.1", "0003:38EB:0001.0002", "0003:000038EB:00000001"),
        ("hidraw2", "1-3", "1-3:1.2", "0003:38EB:0001.0003", "0003:000038EB:00000001"),
        ("hidraw3", "1-1", "1-1:1.0", "0003:340D:1710.0004", "0003:0000340D:00001710"),
    ]
    for node, port, interface, hid, hid_id in devices:
        device = usb1 / port / interface / hid
        (device / "hidraw" / node).mkdir(parents=True)
        (device / "uevent").write_text(f"DRIVER=hid-generic\nHID_ID={hid_id}\n")
        (device / "hidraw" / node / "device").symlink_to(
            os.path.join("..", "..", "..", hid)
        )
        (fake_usb.sysfs / "class" / "hidraw" / node).symlink_to(
            os.path.relpath(
                device / "hidraw" / node, fake_usb.sysfs / "class" / "hidraw"
            )
        )
        (fake_usb.dev / node).write_bytes(b"")

    assert find_beacons() == {"1-1": str(fake_usb.dev / "hidraw3")}


def test_unreadable_entry_logged_once_without_system_text(
    fake_usb: FakeUsb, caplog: pytest.LogCaptureFixture
) -> None:
    """A skipped entry is logged at debug by its node and error type, once."""
    caplog.set_level(logging.DEBUG, logger=usb_beacon.__name__)
    fake_usb.plug("1-1")
    device = (fake_usb.sysfs / "class" / "hidraw" / "hidraw0" / "device").resolve()
    (device / "uevent").unlink()
    (device / "uevent").mkdir()

    assert find_beacons() == {}
    assert find_beacons() == {}

    assert [
        (r.levelno, r.getMessage())
        for r in caplog.records
        if r.name == usb_beacon.__name__
    ] == [
        (
            logging.DEBUG,
            "Skipped hidraw0 in sysfs: it could not be read (IsADirectoryError)",
        )
    ]
    assert "Is a directory" not in caplog.text
