# Beacons plugged into Home Assistant — design

**Status:** approved by the owner 2026-11-03 ("Go and ship" after the architecture section; the
sections after it are the recommendations it accepted). Version to ship: **0.2.0**.

## 1. What and why

Today each beacon is driven by `blinkybeacon-tray` on a Windows or macOS PC, and this
integration reaches it over HTTP. The owner also wants beacons **plugged straight into the Home
Assistant machine** to be driven by the integration itself, with no tray.

Agreed with the owner:

- **A few beacons on one machine (2–4), each with its own meaning** (one per team, for example).
  So each beacon has its own name in Home Assistant.
- **A beacon is known by the USB port it is plugged into.** The beacons are identical and carry
  no serial number, so the port is the only identity. Ports are fixed at an event (a labelled hub,
  set up once).
- **A beacon that disappears from its port stays**, unavailable, with a repair notice, until the
  user removes it. A brief unplug must never erase a name or break an automation. A beacon that
  appears in a different port is a new beacon to be named.
- **Set-up:** offered as soon as it is plugged in when the integration can detect it; otherwise,
  and always as a backup, added by hand from a list of the USB ports holding an unnamed beacon.
- **Same behaviour as a tray beacon:** the light, the "USB connected" sensor and the
  `blinkybeacon.spin` / `flash` / `stop` actions with `duration`, and the same rule that an action
  on a beacon that is down fails with an error naming it.
- **Not now, perhaps later:** a Home Assistant add-on shipped from the BlinkyBeacon project's own
  releases (one beacon driver shared by the tray and Home Assistant). Out of scope here.

## 2. What was measured (2026-11-03, a test machine: Home Assistant OS 18.2, core 2026.10.4)

- The beacon enumerates as a HID device, vendor `0x340d`, product `0x1710`, product name
  "Beacon Light Orange"; the host lists it as `/dev/hidrawN` with
  `HID_ID=0003:0000340D:00001710` in `/sys/class/hidraw/hidrawN/device/uevent`.
- Its USB port is readable from the device's sysfs path: `…/usb1/1-1/1-1:1.0/0003:340D:1710.0004`
  is port `1-1` (the last path element with a `-` and no `:`; behind a hub it reads like `1-3.2`).
- Home Assistant's own process (in its container, uid 0) sees `/sys/class/hidraw` and may write
  `/dev/hidrawN`. A throwaway check wrote the spin report, waited, wrote the stop report: both
  writes took all 10 bytes and **the beacon spun and stopped** (seen by the owner).
- **Home Assistant's USB discovery scans serial ports only** (`homeassistant/components/usb`
  lists serial ports), so a manifest `usb` matcher would never announce this HID device. The
  integration detects beacons itself.
- The protocol (from the BlinkyBeacon project's `pkg/fsbeacon/usbhid.go`): three fixed 10-byte
  output reports, the first byte the report ID `0x00`:
  - spin `00 FF 01 66 C8 FF AD 52 81 D6`
  - flash `00 FF 07 FF 50 FF 1C 8E B0 B8`
  - stop `00 FF 00 00 64 00 32 9E D7 0D`

  The active report is written again every 5 s, as the tray does: the beacon falls idle
  without it, and a failed write is how an unplug is noticed.

## 3. Design

### 3.1 Components

- **`usb_beacon.py` (new), two parts, no new requirement (plain Python, file I/O):**
  - `find_beacons(sysfs_root="/sys") -> dict[str, str]`: every USB port holding a beacon, mapped
    to its `/dev/hidrawN` path. Reads `class/hidraw/*/device/uevent` and the device's real path;
    anything unreadable is skipped, never raised.
  - `UsbBeacon`: drives one beacon on one port. `async spin()`, `flash()`, `stop()` and
    `async status() -> BeaconStatus` — **the same calls `BlinkyBeaconClient` answers**, so the
    coordinator, light, sensor and actions use either kind unchanged. It finds its port's device
    path on each open, writes reports in the executor under one lock, and runs a keepalive that
    writes the active report every 5 s. A failed write or an absent port means **not connected**:
    the device is closed and reopened on the next command or keepalive once the port holds a
    beacon again. After a reopen following a failed write the beacon is written the mode it was in, so a quick replug keeps it spinning; a beacon found again after a longer absence is idle (stop), as a tray after a replug.
- **Config entries:** one per USB beacon, `unique_id = "usb:<port>"`, data `{"usb_port": "1-1"}`,
  title the name the user gives. Tray entries are unchanged.
- **The coordinator** keeps polling every 5 s and gets its status from whichever client the entry
  has. `status()` of a USB beacon is local and fast: the active mode and whether the last write
  or open succeeded and the port still holds a beacon.

### 3.2 Adding a beacon

- **Offered:** while at least one BlinkyBeacon entry is loaded, a scan every 10 s calls
  `find_beacons`; each port holding a beacon with no entry (and no flow already in progress for
  it) starts a discovery flow, "BlinkyBeacon found on USB port 1-1", in Settings → Devices.
- **By hand:** the user step offers "Tray on a PC" (today's form) or "USB beacon"; the latter lists
  the ports holding an unnamed beacon. With none, the step says so and offers the tray form.
- **Naming:** the confirm step flashes the chosen beacon (keepalive included) while it is shown and
  stops it when the step is submitted or abandoned, so the user sees which beacon they are naming;
  the name is required and defaults to "Beacon on USB port 1-1".

### 3.3 When a beacon goes missing

- The light and the sensor show it: the light is unavailable, "USB connected" is off, as for a
  tray whose USB light is unplugged.
- A **repair issue** names the beacon and its port ("<name> is missing from USB port 1-1"); its fix
  removes the beacon's entry after a confirmation. The issue clears by itself when the port holds a
  beacon again.
- An action on a missing beacon fails with the same error naming the beacon as for a tray.
- A beacon in another port is offered as new (3.2); the old entry stays until removed.

### 3.4 Errors and edges

- Every file and device error is caught at the device boundary, logged by its type and the port,
  never by text from the system, and turned into "not connected".
- Two entries can never hold one port (`unique_id`), and a second set-up for a configured port is
  aborted as already configured.
- Unloading an entry stops its keepalive, writes stop if the beacon is connected, and closes the
  device.
- The scan and the keepalives run off the event loop; nothing blocks it.

## 4. Testing

- **Unit, with a fake sysfs tree in a temporary directory and a fake device file:** the bytes of
  each report; `find_beacons` on a direct port, a hub port, other HID devices, unreadable files;
  keepalive timing under a frozen clock; unplug (write error, port gone) to not connected and back;
  status; unload.
- **Flows:** the offered flow (scan with an entry loaded, no duplicate flow, already configured),
  the manual "USB beacon" step with and without beacons, the flash while naming and the stop after.
- **Repairs:** raised when the port empties, cleared on return, the fix removes the entry.
- **Actions and entities:** spin, flash, stop with `duration` on a USB beacon; the error naming a
  missing beacon; tray beacons unchanged (every existing test green, unmodified).
- **Negative environment:** the suite once in a copy with no `.git`, recorded.
- **Real hardware, at the end:** on the owner's test machine with a beacon in a fixed port: add it
  by hand and through the offer, spin, flash, stop, a `duration`, the owner unplugging and
  replugging it; recorded in the plan's last task.

## 5. Shipping

Version `0.2.0` in `manifest.json` and `pyproject.toml`; the README gains a "Beacons plugged into
Home Assistant" section (set-up, ports, the missing-beacon notice) and the troubleshooting note
carried since 0.1.0. Shipped to the public standalone repository with a release, so HACS offers
the update. This folder's repository is public: no file or commit message here names an event,
a person or a host.
