# Beacons plugged into Home Assistant — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drive BlinkyBeacon USB beacons plugged straight into the Home Assistant machine, with no tray, through the same light, "USB connected" sensor and `blinkybeacon.spin` / `flash` / `stop` actions as a tray beacon. Each beacon is known by its USB port, offered when it is plugged in or added by hand, and kept with a repair notice while it is missing.

**Architecture:** A new `usb_beacon.py` finds beacons by reading sysfs (`find_beacons`) and drives one beacon per port (`UsbBeacon`). It answers the same four calls as the tray client (`status`, `spin`, `flash`, `stop`), so the coordinator, light, sensor and actions take either kind unchanged. A USB entry is `unique_id = "usb:<port>"`, data `{"usb_port": "<port>"}`. `repairs.py` raises a fixable notice while a USB beacon is missing; `usb_scan.py` offers unnamed beacons every 10 s while any entry is loaded. The config flow gains a menu (tray or USB), a port picker, an offer step and a naming step that flashes the beacon.

**Tech Stack:** Python 3.14, Home Assistant 2026.10.4, `pytest-homeassistant-custom-component==0.13.375`, `freezegun` (through it), ruff 0.17.2. Plain Python file I/O for the device; no new requirement.

**Spec:** `blinkybeacon-hassio/docs/superpowers/specs/2026-11-03-usb-beacons-design.md` (approved by the owner 2026-11-03). Executors read the spec whole before their task.

**How this plan was checked:** every task below was assembled from `main` (`d425604`) in a scratch copy, in order. Each task's test step was run and its red state recorded here, then its code step, green. The whole suite, `ruff check` and `ruff format --check` were clean after each task. The plan's code and tests are the files that ran; the counts quoted are from that run.

## Global Constraints

- **Paths.** `W` is the worktree's path; folder `BB=$W/blinkybeacon-hassio`, branch `wt/blinkybeacon-usb`. `NAMES_LIST` and `SECRETS_LIST` are the two check files, the names list and the secrets list, kept outside every repository; their paths are given in the kickoff and kept out of this public folder. Every git command is `git -C "$W" …`; check each commit lands on `wt/blinkybeacon-usb`. Never `cd` in the session; a command that needs a working directory runs in a subshell, `(cd "$BB" && …)`. Never commit in the primary checkout.
- **Gates run from `blinkybeacon-hassio/`:** `(cd "$BB" && timeout 300 .venv/bin/pytest -q -p no:cacheprovider)`, `(cd "$BB" && .venv/bin/ruff check custom_components tests)`, `(cd "$BB" && .venv/bin/ruff format --check custom_components tests)`. The `.venv` is made as the folder's README → Development says (`~/.local/bin/uv`, Python 3.14); never bare `python3`.
- **Versions do not change.** `manifest.json` and `pyproject.toml` stay at `0.1.0`; the spec's `0.2.0` is set by the master at ship. `manifest.json` is not touched at all: no new requirement (spec §3.1: "no new requirement (plain Python, file I/O)").
- **The protocol (spec §2):** HID ID `0003:0000340D:00001710`; reports `spin 00 FF 01 66 C8 FF AD 52 81 D6`, `flash 00 FF 07 FF 50 FF 1C 8E B0 B8`, `stop 00 FF 00 00 64 00 32 9E D7 0D`; "The active report is written again every 5 s".
- **Identity (spec §3.1):** "one per USB beacon, `unique_id = "usb:<port>"`, data `{"usb_port": "1-1"}`, title the name the user gives. Tray entries are unchanged."
- **The scan (spec §3.2):** "while at least one BlinkyBeacon entry is loaded, a scan every 10 s calls `find_beacons`".
- **Tray beacons keep working exactly as in 0.1.0.** The 0.1.0 test files (`test_api.py`, `test_binary_sensor.py`, `test_config_flow.py`, `test_init.py`, `test_light.py`, `test_services.py`) are never edited; `tests/conftest.py` only gains lines (`git -C "$W" diff main -- blinkybeacon-hassio/tests/conftest.py` shows no `-` line).
- **Tests touch no real device and no real `/sys`.** An autouse fixture points the USB code at a fake sysfs and `/dev` under the test's temporary directory; sockets stay disabled; durations use `freezer` and Home Assistant's time helpers, never the wall clock.
- **This folder's repository is public.** No file and no commit message may name an event, a person, a host or a product of the owner's other projects; examples are generic ("Team A beacon", "a booth"). Before every push: `command grep -c -i -F -f "$NAMES_LIST" <every file the task created or changed>` → `0` each, `git -C "$W" log --format=%B main..wt/blinkybeacon-usb | command grep -c -i -F -f "$NAMES_LIST"` → `0`, `git -C "$W" log -p main..wt/blinkybeacon-usb | command grep -c -F -f "$SECRETS_LIST"` → `0`.
- **Product text** (strings, README), docstrings and code comments carry no process vocabulary: no task numbers, ruling codes, review or plan references, no exception text. Device errors are logged by their type and the port, never by text from the system (spec §3.4).
- `strings.json` and `translations/en.json` are identical after every task (`cmp` silent).
- Commits are path-scoped (`git add <paths>` then `git commit -m … -- <paths>`), carry no AI attribution, and are pushed after each task: `git -C "$W" push origin wt/blinkybeacon-usb`. Never push to a standalone repository, never to `main`, no tag.

## Decisions this plan makes (for the master's gate)

The spec decides the design; these are the places where it is silent, where its lines pull against each other or against the kickoff, or where the assembly found a fact it did not know. Each is built as written below unless the gate rules otherwise.

**D1 — The first step shows the menu only when a USB beacon is waiting.** The spec says one thing, the existing tests another:

| Spec §3.2 | Spec §4 and the kickoff |
|---|---|
| "By hand: the user step offers 'Tray on a PC' (today's form) or 'USB beacon'; the latter lists the ports holding an unnamed beacon. With none, the step says so and offers the tray form." | "tray beacons unchanged (every existing test green, unmodified)"; kickoff: "every 0.1.0 test still green and unmodified" |

Seven 0.1.0 flow tests start the `user` step, assert a form, and submit the tray fields to it; a menu at `user` fails all seven. So: `user` shows the menu (*Into a PC running blinkybeacon-tray* / *Into this Home Assistant*) when at least one plugged-in beacon has no entry, and goes straight to the tray form otherwise. The tray form's text says a beacon plugged into Home Assistant is offered as a choice there once plugged in. If the menu was shown and the beacon is gone when *Into this Home Assistant* is picked, the tray form opens with the error "No beacon without a name is plugged into this Home Assistant…": that is the spec's "with none, the step says so and offers the tray form". The tray form moves from step id `user` to `tray`; no 0.1.0 test checks a step id. *Serves:* tray users see no change; *costs:* nothing the spec asks for, as far as the plan can tell.

**D2 — The offer's first step lights nothing; the naming step flashes.** Home Assistant runs a discovery flow's first step when the flow is created, before anyone opens it. If that step flashed, a beacon would flash from the moment it was plugged in until its offer was dealt with. So the offered flow is: *BlinkyBeacon found on USB port 1-1* → a confirm form (nothing lights) → the naming form (flashes, as spec §3.2 says). Opening an offer whose beacon was unplugged in the meantime closes it with "The beacon is no longer plugged into USB port 1-1." The manual path is menu → port list → naming form.

**D3 — The USB port rule is tightened.** Spec §2: "the last path element with a `-` and no `:`". The assembly found that rule also matches path parts that are not USB ports: a device off USB whose sysfs path ran through the test's temporary directory got the "port" `pytest-3825`, a part of that directory's name. The plan takes the last path part named as Linux names a USB device, `bus-port[.port…]` (`\d+-\d+(?:\.\d+)*`): `1-1` and `1-3.2` as in the spec, the same answer on every real USB path, and no port for a device off USB.

**D4 — The action error for a USB beacon has its own text.** Spec §3.3: "An action on a missing beacon fails with the same error naming the beacon as for a tray." The tray's message is "The beacon light of {name} is not plugged into its PC ({address})", which would be wrong for a beacon plugged into Home Assistant, and a 0.1.0 test pins that text. So a USB beacon's errors are the same kind, raised in the same places, naming the beacon, with their own keys: `usb_not_plugged_in` "{name} is not plugged into USB port {port}." and `usb_not_loaded` "{name} on USB port {port} is not loaded. Check its entry under Settings > Devices & services." Several beacons failing still give `commands_failed` with their names.

**D5 — Reconfigure on a USB beacon aborts.** The spec does not mention it. The 0.1.0 reconfigure step (host and port) is offered on every entry; on a USB entry it would add tray fields. It aborts with "A beacon plugged into this Home Assistant is known by its USB port, so there is nothing to change here. To use another port, plug it in there, add it, and remove this one."

**D6 — Test seams.** `find_beacons(sysfs_root=None, dev_root=None)` reads the module's `SYSFS_ROOT` (`/sys`) and `DEV_ROOT` (`/dev`) at call time when no root is given. It keeps the spec's name and meaning, `find_beacons(sysfs_root=…)`, with the roots as `Path`s and a second root for `/dev`, where the spec shows a string default. Reports go through the module's `_write_report` (`os.write`). The tests point all three at a fake machine under the temporary directory. A regular file stands in for `/dev/hidrawN`; a write error on an open device, which only the kernel can cause, is made by the fake's `write_error`.

**D7 — The missing notice also clears when its entry unloads.** It is raised again by setup if the beacon is still missing. A disabled beacon therefore carries no notice. The spec's rule, "The issue clears by itself when the port holds a beacon again", holds.

**D8 — Small calls.** The `already_configured` abort text becomes "This beacon is already added." (shared by both kinds; no test checks it). A USB beacon's device has model "USB beacon" and no configuration URL. The naming form's flash has no time limit: it lasts while the form is open and stops when it is submitted or closed (spec: "while it is shown"); a browser that dies without closing the form leaves the flow, and the flash, until Home Assistant restarts. Home Assistant stopping does nothing new for a USB beacon (as 0.1.0, a pending timed stop is sent); the beacon falls idle once its keepalive ends (spec §2).

**Questions for the master:** none block the build. D1 and D4 are the two where the plan reads the spec; the rest fill silence.

## Review Focus

The five uncovered-by-the-spec conditions most likely to bite someone using this, each pinned by a test in the task named:

- **A keepalive that fires while a command or a close is running.** The keepalive must write the mode as it is when it gets the device, never an older one, and must not reopen a beacon that has just closed. Tests `test_keepalive_never_writes_an_older_mode`, `test_keepalive_queued_behind_close_does_not_reopen` (Task 2); both were checked to fail on the bug they guard.
- **A beacon replugged into the same port comes back as another `/dev/hidrawN`.** It must be found again by its port, never by its old device file. Tests `test_unplug_and_replug_on_another_node` (Task 2), `test_unplug_and_replug` (Task 3).
- **The naming form closed without an answer.** The beacon must stop for good, with no later keepalive. Test `test_closing_the_naming_step_stops_the_beacon` (Task 5).
- **sysfs that cannot be read, is not text, or is not USB.** The device is skipped and the others are still found, never an exception. Tests `test_find_skips_what_it_cannot_read`, `test_find_off_usb_is_skipped`, `test_find_without_hidraw_class` (Task 1).
- **Home Assistant starting before the beacon is plugged in.** The entry loads (no retry loop), the light is unavailable, the notice is raised, and plugging the beacon in brings it back within two 5-second ticks. Tests `test_missing_at_setup_loads_unavailable` (Task 3), `test_raised_at_startup_when_missing` (Task 4).

## Plan gate checklist (agent rules)

1. *Numeric modules:* none; the reports are fixed bytes, pinned whole in Task 1.
2. *Hunks that send to a platform:* the device writes. Payload checklist in Task 2: each report exactly 10 bytes, report ID `0x00` first; a write counts only if all 10 bytes went; the two clients answer the same four calls, the USB one raises only `BlinkyBeaconNotConnectedError`; the fake `write(fd, report) -> int` has `os.write`'s signature.
3. *Loader or parser tasks:* `find_beacons` (Task 1) is tested on a real-shape sysfs (the measured path and a kernel-shaped `uevent`, keys present and omitted). Task 1 ends with a read-only smoke on this machine's `/sys`. The real machine is read by the master's hardware smoke (Task 7, M2).
4. *Tests that import the package:* the suite runs once in a copy with no `.git` (Task 7).
5. *Controller-authored hunks:* none.

## File structure

| File | Task | Responsibility |
|---|---|---|
| `custom_components/blinkybeacon/usb_beacon.py` (new) | 1, 2 | Find beacons in sysfs by port; drive one beacon: reports, keepalive, unplug and replug |
| `custom_components/blinkybeacon/const.py` | 2, 3, 6 | `KEEPALIVE_INTERVAL`, `CONF_USB_PORT`, `USB_SCAN_INTERVAL` |
| `custom_components/blinkybeacon/__init__.py` | 3, 4, 6 | Build a tray client or a `UsbBeacon` per entry; track the notice; start the scan |
| `custom_components/blinkybeacon/coordinator.py` | 3 | Either client; errors naming a USB beacon and its port |
| `custom_components/blinkybeacon/entity.py` | 3 | Device info for a USB beacon |
| `custom_components/blinkybeacon/repairs.py` (new) | 4 | The missing notice and its fix flow |
| `custom_components/blinkybeacon/config_flow.py` | 5, 6 | Menu, tray step, port picker, offer, naming with flash; reconfigure guard |
| `custom_components/blinkybeacon/usb_scan.py` (new) | 6 | The 10-second scan that starts offers |
| `custom_components/blinkybeacon/strings.json`, `translations/en.json` | 3, 4, 5, 6 | Errors, notice, flow text (identical files) |
| `tests/fake_usb.py` (new) | 1 | A fake sysfs and `/dev`, the reports, the clock helper `tick()` |
| `tests/conftest.py` | 1, 2, 3 | Gains the autouse `fake_usb` fixture and `usb_entry` |
| `tests/test_usb_find.py` (new) | 1 | Reports, port rule, `find_beacons` |
| `tests/test_usb_beacon.py` (new) | 2 | `UsbBeacon` |
| `tests/test_usb_entry.py` (new) | 3 | A USB entry: setup, entities, actions, errors, device |
| `tests/test_repairs.py` (new) | 4 | The notice and its fix |
| `tests/test_usb_config_flow.py` (new) | 5 | Adding by hand |
| `tests/test_usb_discovery.py` (new) | 6 | Offers |
| `README.md` | 7 | Beacons plugged into Home Assistant; troubleshooting |

All paths below are relative to `blinkybeacon-hassio/`.

## Amendments

The master's plan gate, round 1 (2026-11-03), ruled **FIX FIRST**: fold U1–U7, then build. **Where an amendment and a task's body differ, the amendment wins.** Each amendment below says which task builds it and gives its exact code. Every amendment was assembled from `main` with the tasks, in order, before this table was committed. The new counts: Task 1 green 91, Task 2 103, Task 3 113 (red 10 failed), Task 4 118, Task 5 132 (red 14 failed), Task 6 142 (red 6 failed, 4 passed). ruff and the format check were clean after every task.

| # | Date | Source | Ruling | Tasks touched |
|---|---|---|---|---|
| G1 | 2026-11-03 | Plan gate, round 1 | D1–D7 accepted as the plan recommends. D1 stands as reading spec §3.2 together with §4: the menu whenever a USB beacon is waiting, the tray form's note, and the `no_usb_beacon` error. D6 stands with U5. D8 is accepted except its flash, which U1 replaces. | — |
| U1 | 2026-11-03 | Plan gate, round 1 (Important) | The naming flash stops by itself **2 minutes** after the naming form was last shown, as well as on submit and when the flow is removed. Showing the form again, by any route (first show, a refused name, the UI opening the flow again), restarts the 2 minutes, and starts the flash again if it had stopped. An offered flow the user opens and then closes therefore stops flashing within 2 minutes. The constant is `NAMING_FLASH_TIMEOUT = timedelta(minutes=2)`. Two tests under the frozen clock. The text and README say "or after 2 minutes". The hand-run steps gain M10. | 5, 7 (and the import order in 6) |
| U2 | 2026-11-03 | Plan gate, round 1 (Minor) | One test built on the measured layout: `class/hidraw/hidrawN` a relative link into the device tree, the device's `hidraw/hidrawN/device` link back to it, three `HID_ID=0003:000038EB:00000001` interfaces on port `1-3` as hidraw0–2 and the beacon on `1-1` as hidraw3; `find_beacons` returns only `{"1-1": …/hidraw3}`. | 1 |
| U3 | 2026-11-03 | Plan gate, round 1 (Minor) | The README says what was measured: on Home Assistant OS, Home Assistant's own process can write these devices. It no longer says the integration was tested there. The master confirms or extends the sentence after the hand-run steps. | 7 |
| U4 | 2026-11-03 | Plan gate, round 1 (Minor) | `beacon_error` for a USB entry falls back to `usb_not_plugged_in` for a key with no USB text of its own, instead of raising `KeyError`; a test with `unexpected_reply`. | 3 |
| U5 | 2026-11-03 | Plan gate, round 1 (Minor) | `find_beacons` takes its roots as strings or paths (`Path(sysfs_root)`, `Path(dev_root)`), so the spec's `find_beacons("/sys")` works; a test with strings. | 1 (and 2, whose whole-file replacement carries it) |
| U6 | 2026-11-03 | Plan gate, round 1 (Minor) | A sysfs entry skipped as unreadable is logged at debug, by the entry's node name and the error's type, never the system's text, once per node and error type for the life of the process. The 10-second scan and the 5-second status reads therefore do not repeat it. The autouse fixture gives each test a fresh memo. A test with `caplog`. | 1, 2 |
| U7 | 2026-11-03 | Plan gate, round 1 (Minor) | Two behaviours pinned: the writes of an offered beacon through to its entry, `[STOP, FLASH, STOP, STOP]` (the flash, its stop on submit, the entry's start); and a port being named by hand is not offered meanwhile. | 6 |

### U1 — the naming flash stops after 2 minutes (Task 5; Task 6's import; Task 7)

- **Task 5, `const.py`:** add `NAMING_FLASH_TIMEOUT = timedelta(minutes=2)` as the file's last line, after `KEEPALIVE_INTERVAL = timedelta(seconds=5)`. Task 6 then inserts `USB_SCAN_INTERVAL` between them as its body says. Task 5's Files gain `const.py`.
- **Task 5 Step 3 writes this `config_flow.py`** instead of the body's. It is the body's file with the `datetime`, `CALLBACK_TYPE`, `HassJob` and `async_call_later` imports, the `.const` import as a block, `self._cancel_flash_timeout` in `__init__`, `async_step_name` flashing through `_async_flash()` on every show, and `_async_flash`, `_async_flash_timeout`, `_async_cancel_flash_timeout`, with `async_remove` and `_async_stop_flashing` cancelling the timer:

```python
"""Add a beacon from the UI: on a PC running the tray, or plugged in here."""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import CALLBACK_TYPE, HassJob, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later
import voluptuous as vol

from .api import (
    BlinkyBeaconClient,
    BlinkyBeaconConnectionError,
    BlinkyBeaconError,
    BlinkyBeaconNotConnectedError,
)
from .const import (
    CONF_USB_PORT,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DOMAIN,
    NAMING_FLASH_TIMEOUT,
)
from .usb_beacon import UsbBeacon, find_beacons, usb_unique_id

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
    }
)
RECONFIGURE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
    }
)


def normalize_host(raw: str, port: int) -> tuple[str, int]:
    """Reduce what was typed in the host field to a host and a port.

    Accepts a bare host, host:port, [ipv6]:port, a bare IPv6 address, or any of
    these as an http(s) URL with a trailing slash. Raises ValueError otherwise.
    """
    value = raw.strip()
    for scheme in ("http://", "https://"):
        if value.lower().startswith(scheme):
            value = value[len(scheme) :]
    value = value.rstrip("/")
    if not value or "/" in value:
        raise ValueError(raw)

    if value.startswith("["):
        host, sep, rest = value[1:].partition("]")
        if not sep:
            raise ValueError(raw)
        if rest:
            if not rest.startswith(":"):
                raise ValueError(raw)
            port = _port(rest[1:], raw)
    elif value.count(":") == 1:
        host, _, port_text = value.partition(":")
        port = _port(port_text, raw)
    else:
        host = value
    if not host:
        raise ValueError(raw)
    return host, port


def _port(text: str, raw: str) -> int:
    if not text.isdigit() or not 1 <= int(text) <= 65535:
        raise ValueError(raw)
    return int(text)


class BlinkyBeaconConfigFlow(ConfigFlow, domain=DOMAIN):
    """One flow per beacon: a tray on a PC, or a beacon in a USB port here."""

    VERSION = 1

    def __init__(self) -> None:
        self._usb_port = ""
        self._flasher: UsbBeacon | None = None
        self._cancel_flash_timeout: CALLBACK_TYPE | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask where the beacon is plugged in, if a USB beacon is waiting."""
        if await self._async_unnamed_ports():
            return self.async_show_menu(step_id="user", menu_options=["tray", "usb"])
        return await self.async_step_tray()

    async def async_step_tray(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the tray's address and a name for the beacon."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                host, port = normalize_host(
                    user_input[CONF_HOST], user_input[CONF_PORT]
                )
            except ValueError:
                errors[CONF_HOST] = "invalid_host"
            else:
                await self.async_set_unique_id(f"{host}:{port}".lower())
                self._abort_if_unique_id_configured()
                if not (error := await self._async_check(host, port)):
                    return self.async_create_entry(
                        title=user_input[CONF_NAME],
                        data={CONF_HOST: host, CONF_PORT: port},
                    )
                errors["base"] = error

        return self.async_show_form(
            step_id="tray",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_usb(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """List the USB ports holding a beacon with no name yet."""
        ports = await self._async_unnamed_ports()
        if not ports:
            return self.async_show_form(
                step_id="tray",
                data_schema=USER_SCHEMA,
                errors={"base": "no_usb_beacon"},
            )
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_USB_PORT] in ports:
                self._usb_port = user_input[CONF_USB_PORT]
                await self.async_set_unique_id(
                    usb_unique_id(self._usb_port), raise_on_progress=False
                )
                self._abort_if_unique_id_configured()
                return await self.async_step_name()
            errors["base"] = "usb_beacon_gone"
        return self.async_show_form(
            step_id="usb",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USB_PORT): vol.In(
                        {port: f"USB port {port}" for port in ports}
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_name(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Flash the beacon while the user names it."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if name := user_input[CONF_NAME].strip():
                await self._async_stop_flashing()
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=name, data={CONF_USB_PORT: self._usb_port}
                )
            errors[CONF_NAME] = "name_required"
        await self._async_flash()
        return self.async_show_form(
            step_id="name",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME, default=f"Beacon on USB port {self._usb_port}"
                    ): str
                }
            ),
            description_placeholders={"port": self._usb_port},
            errors=errors,
        )

    @callback
    def async_remove(self) -> None:
        """Stop the beacon if the naming step was left without an answer."""
        self._async_cancel_flash_timeout()
        if (flasher := self._flasher) is not None:
            self._flasher = None
            self.hass.async_create_task(flasher.async_close())

    async def _async_flash(self) -> None:
        """Flash the beacon being named, until 2 minutes after the form is shown."""
        if self._flasher is None:
            self._flasher = UsbBeacon(self.hass, self._usb_port)
            await self._flasher.async_start()
            with suppress(BlinkyBeaconNotConnectedError):
                await self._flasher.flash()
        self._async_cancel_flash_timeout()
        self._cancel_flash_timeout = async_call_later(
            self.hass,
            NAMING_FLASH_TIMEOUT,
            HassJob(self._async_flash_timeout, cancel_on_shutdown=True),
        )

    async def _async_flash_timeout(self, _now: datetime) -> None:
        self._cancel_flash_timeout = None
        await self._async_stop_flashing()

    async def _async_stop_flashing(self) -> None:
        self._async_cancel_flash_timeout()
        if (flasher := self._flasher) is not None:
            self._flasher = None
            await flasher.async_close()

    @callback
    def _async_cancel_flash_timeout(self) -> None:
        if self._cancel_flash_timeout is not None:
            self._cancel_flash_timeout()
            self._cancel_flash_timeout = None

    async def _async_unnamed_ports(self) -> list[str]:
        """Ports holding a beacon no entry names; an ignored offer names none."""
        ports = await self.hass.async_add_executor_job(find_beacons)
        named = self._async_current_ids(include_ignore=False)
        return sorted(port for port in ports if usb_unique_id(port) not in named)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Point an existing beacon at its tray's new address."""
        entry = self._get_reconfigure_entry()
        if CONF_USB_PORT in entry.data:
            return self.async_abort(reason="usb_not_reconfigurable")
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                host, port = normalize_host(
                    user_input[CONF_HOST], user_input[CONF_PORT]
                )
            except ValueError:
                errors[CONF_HOST] = "invalid_host"
            else:
                unique_id = f"{host}:{port}".lower()
                await self.async_set_unique_id(unique_id)
                if unique_id != entry.unique_id:
                    self._abort_if_unique_id_configured()
                if not (error := await self._async_check(host, port)):
                    return self.async_update_reload_and_abort(
                        entry,
                        unique_id=unique_id,
                        data_updates={CONF_HOST: host, CONF_PORT: port},
                    )
                errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                RECONFIGURE_SCHEMA, user_input or entry.data
            ),
            errors=errors,
        )

    async def _async_check(self, host: str, port: int) -> str | None:
        """Read /status once; return an error key, or None if the tray answered."""
        client = BlinkyBeaconClient(async_get_clientsession(self.hass), host, port)
        try:
            await client.status()
        except BlinkyBeaconConnectionError:
            return "cannot_connect"
        except BlinkyBeaconError:
            return "invalid_reply"
        return None
```

- **Task 5 Step 4 (b):** the `name` step's description ends "It stops when you submit or close this form, or after 2 minutes." in place of "It stops when you submit or close this form." (both files; `cmp` silent).
- **Task 5 Step 1:** `tests/test_usb_config_flow.py` gains, at its end:

```python
async def test_naming_flash_stops_after_two_minutes(
    hass: HomeAssistant, fake_usb: FakeUsb, freezer: FrozenDateTimeFactory
) -> None:
    """A naming form left open stops the flash 2 minutes after it was shown."""
    fake_usb.plug("1-1")
    result = await _to_name(hass)

    await tick(hass, freezer, 119)
    assert fake_usb.written()[-1] == FLASH

    await tick(hass, freezer, 1)
    assert fake_usb.written()[-1] == STOP
    written = len(fake_usb.written())

    await tick(hass, freezer, 30)
    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()
    assert len(fake_usb.written()) == written


async def test_showing_the_naming_form_again_restarts_the_two_minutes(
    hass: HomeAssistant, fake_usb: FakeUsb, freezer: FrozenDateTimeFactory
) -> None:
    """Each time the naming form is shown, the flash runs 2 more minutes."""
    fake_usb.plug("1-1")
    result = await _to_name(hass)
    await tick(hass, freezer, 60)

    # Opening the form again in the UI runs its step again with no input.
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["step_id"] == "name"
    await tick(hass, freezer, 61)
    assert fake_usb.written()[-1] == FLASH

    await tick(hass, freezer, 59)
    assert fake_usb.written()[-1] == STOP
    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()
```

  Both were checked against mutations: with the timer never started, both fail; with a show not restarting it, the second fails.
- **Task 6 Step 6:** the import `from homeassistant.helpers.typing import DiscoveryInfoType` goes after `from homeassistant.helpers.event import async_call_later`, which ruff's order puts after `aiohttp_client`.
- **Task 7 Step 1:** the README's flash sentence reads "…it stops when you submit or close the form, or 2 minutes after the form was last shown." (in the body's replacement (6), the new section).
- **Task 7 Step 7** gains **M10 — the flash ends by itself.** With a second beacon offered (or the first moved to a free port, as in M6), open the offer, go on to the naming step so the beacon flashes, then close the dialog without submitting **(owner)**: the beacon stops within 2 minutes **(owner times it)**.

### U2, U5, U6 — sysfs read the measured way, roots as strings, skips logged once (Task 1; Task 2)

- **Task 1 Step 5 writes this `usb_beacon.py`** instead of the body's. It is the body's file with `import logging`, `_LOGGER`, `_SKIPS_LOGGED`, roots taken as `str | os.PathLike[str]`, and `_log_skipped`:

```python
"""Beacons plugged into this machine's USB ports, driven without a tray.

The beacon is a HID device that takes three fixed 10-byte output reports. It
falls idle unless its report is written again every few seconds, and a write
that fails is how an unplugged beacon shows.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import re

from .const import STATE_FLASH, STATE_IDLE, STATE_SPIN

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

    Anything that cannot be read is skipped, and logged once. This reads files:
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
```

- **Task 1 Step 3 writes this `tests/test_usb_find.py`** instead of the body's. It is the body's file with `import logging`, `import os` and `from custom_components.blinkybeacon import usb_beacon` added, and three tests at its end: `test_find_takes_roots_as_strings` (U5), `test_find_on_the_measured_layout` (U2), `test_unreadable_entry_logged_once_without_system_text` (U6):

```python
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
    uevent.write_text(uevent.read_text().replace("0000340D", "0000340d"))

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
    """The roots may be given as strings, as paths are written in the spec."""
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
```

- **Task 1 Step 2:** the `fake_usb` fixture gains, after its `DEV_ROOT` line, `monkeypatch.setattr(usb_beacon, "_SKIPS_LOGGED", set())`.
- **Task 2 Step 1:** the `_write_report` line goes after that `_SKIPS_LOGGED` line, so the fixture ends:

```python
    monkeypatch.setattr(usb_beacon, "SYSFS_ROOT", fake.sysfs)
    monkeypatch.setattr(usb_beacon, "DEV_ROOT", fake.dev)
    monkeypatch.setattr(usb_beacon, "_SKIPS_LOGGED", set())
    monkeypatch.setattr(usb_beacon, "_write_report", fake.write)
    return fake
```

- **Task 2 Step 5 writes this `usb_beacon.py`** instead of the body's (the Task 1 file above plus the body's Task 2 additions):

```python
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

    Anything that cannot be read is skipped, and logged once. This reads files:
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
        self._fd: int | None = None
        self._mode = STATE_IDLE
        self._closed = False
        self._last_error: str | None = None
        self._cancel_keepalive: CALLBACK_TYPE | None = None

    async def async_start(self) -> None:
        """Set the beacon idle, then keep writing its mode."""
        await self._async_write(STATE_IDLE)
        self._cancel_keepalive = async_track_time_interval(
            self._hass,
            self._async_keepalive,
            KEEPALIVE_INTERVAL,
            name=f"BlinkyBeacon USB port {self.port}",
            cancel_on_shutdown=True,
        )

    async def async_close(self) -> None:
        """Stop the keepalive, stop the beacon if it is there, and close it."""
        if self._cancel_keepalive is not None:
            self._cancel_keepalive()
            self._cancel_keepalive = None
        async with self._lock:
            self._closed = True
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
        """Write a mode's report, or the current mode's; False if not taken."""
        async with self._lock:
            if self._closed:
                return False
            mode = self._mode if mode is None else mode
            if await self._hass.async_add_executor_job(self._write, REPORTS[mode]):
                self._mode = mode
                return True
            self._mode = STATE_IDLE
            return False

    def _write(self, report: bytes) -> bool:
        """Write one report, opening the device first if it is closed."""
        try:
            if self._fd is None:
                if (path := find_beacons().get(self.port)) is None:
                    return False
                self._fd = os.open(path, os.O_WRONLY | os.O_CLOEXEC)
            written = _write_report(self._fd, report)
        except OSError as err:
            self._failed(type(err).__name__)
            return False
        if written != len(report):
            self._failed("short write")
            return False
        self._last_error = None
        return True

    def _stop_and_close(self) -> None:
        if self._fd is not None:
            try:
                _write_report(self._fd, REPORTS[STATE_IDLE])
            except OSError as err:
                self._failed(type(err).__name__)
        self._close()

    def _failed(self, kind: str) -> None:
        self._close()
        if kind != self._last_error:
            self._last_error = kind
            _LOGGER.warning(
                "The beacon on USB port %s did not take a report (%s)", self.port, kind
            )

    def _close(self) -> None:
        if self._fd is not None:
            with suppress(OSError):
                os.close(self._fd)
            self._fd = None
```

- **Task 1 green:** `91 passed`; Task 2 green `103 passed`.

### U3 — the README says what was measured (Task 7)

- In Task 7 Step 1, replacement (6) of the body (the new section "Beacons plugged into Home Assistant") reads, in its first paragraph:

```markdown
A beacon can also be plugged straight into a USB port of the machine running Home Assistant.
The integration drives it itself; no tray is needed. Several beacons can be plugged in at
once, each with its own name, for example one per team. On Home Assistant OS, Home
Assistant's own process can write the machine's `/dev/hidraw*` devices, which is what the
integration needs; another installation needs the same.
```

  in place of the body's "…This was tested on Home Assistant OS; another installation needs Home Assistant's own process to be able to write the machine's `/dev/hidraw*` devices." The rest of the replacement is unchanged except U1's flash sentence.

### U4 — an error with no USB text of its own still names the beacon (Task 3)

- **Task 3 Step 6:** in `coordinator.py`'s `beacon_error`, `translation_key=USB_ERRORS[key],` becomes `translation_key=USB_ERRORS.get(key, "usb_not_plugged_in"),`.
- **Task 3 Step 2:** `tests/test_usb_entry.py` gains the import `from custom_components.blinkybeacon.coordinator import beacon_error` (after the `const` import) and, at its end:

```python
def test_error_without_usb_text_names_the_beacon(usb_entry: MockConfigEntry) -> None:
    """An error with no USB text of its own still names the beacon and its port."""
    err = beacon_error(usb_entry, "unexpected_reply")

    assert err.translation_key == "usb_not_plugged_in"
    assert err.translation_placeholders == {"name": "Team A beacon", "port": "1-1"}
```

- **Task 3:** red `10 failed` (the new test fails too, since `main`'s `beacon_error` knows no USB entry; the nine others as recorded); green `113 passed`. Task 4 green `118 passed`.

### U7 — the offered path's writes, and no offer while a port is being named (Task 6)

- **Task 6 Step 1:** in `test_offer_flashes_on_the_naming_step_and_adds`, after its last assertion add `assert fake_usb.written() == [STOP, FLASH, STOP, STOP]`; and at the file's end:

```python
async def test_port_being_named_by_hand_is_not_offered(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    tray: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A beacon being named by hand is not offered a second time meanwhile."""
    fake_usb.plug("1-1")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "usb"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"usb_port": "1-1"}
    )
    assert result["step_id"] == "name"

    await tick(hass, freezer, 10)

    assert _offers(hass) == []
    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()
```

- **Task 6:** red `6 failed, 4 passed` (the new test passes before the scan exists, since nothing scans); green `142 passed`. Task 7 Step 4 and Step 5 expect `142 passed`.

### What each task's dispatch carries

Task 1: U2, U5, U6. Task 2: U5, U6 (the fixture order, the whole file). Task 3: U4. Task 4: the count only. Task 5: U1. Task 6: U1 (import order), U7. Task 7: U1 (README, M10), U3, the counts.

---

### Task 1: Find beacons in USB ports

**Files:**
- Create: `tests/fake_usb.py`, `tests/test_usb_find.py`, `custom_components/blinkybeacon/usb_beacon.py`
- Modify: `tests/conftest.py` (lines added only)

**Interfaces:**
- Consumes: `STATE_SPIN`, `STATE_FLASH`, `STATE_IDLE` from `const.py`.
- Produces (`usb_beacon.py`): `SYSFS_ROOT: Path = Path("/sys")`, `DEV_ROOT: Path = Path("/dev")`, `BEACON_HID_ID = "0003:0000340D:00001710"`, `REPORTS: dict[str, bytes]` keyed `"spin"`, `"flash"`, `"idle"`, `usb_unique_id(port: str) -> str` (`"usb:<port>"`), `usb_port(sysfs_path: str) -> str | None`, `find_beacons(sysfs_root: Path | None = None, dev_root: Path | None = None) -> dict[str, str]` (port → device file path; blocking, run in the executor; never raises).
- Produces (`tests/fake_usb.py`): `FakeUsb(root: Path)` with `.sysfs`, `.dev`, `plug(port, node="hidraw0", hid_id=BEACON_HID_ID, controller=…) -> Path`, `unplug(node="hidraw0")`, `written(node="hidraw0") -> list[bytes]`, `write(fd, report) -> int` (stands in for `os.write`; fails while `.write_error` is set, writes 5 bytes while `.short_writes`), constants `BEACON_HID_ID`, `KEYBOARD_HID_ID`, `SPIN`, `FLASH`, `STOP`, and `async tick(hass, freezer, seconds)` (moves the frozen clock, fires timers, waits for background tasks too).
- Produces (`tests/conftest.py`): autouse fixture `fake_usb -> FakeUsb` that sets `usb_beacon.SYSFS_ROOT` and `usb_beacon.DEV_ROOT` to the fake.

- [x] **Step 1: Write the fake machine.** Create `tests/fake_usb.py`:

```python
"""A fake sysfs and /dev in a temporary directory, laid out as Linux lists them."""

from __future__ import annotations

from datetime import timedelta
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

        A device has no position, so each report goes after the ones before it,
        even through a newly opened descriptor.
        """
        if self.write_error is not None:
            raise self.write_error
        os.lseek(fd, 0, os.SEEK_END)
        if self.short_writes:
            return os.write(fd, report[:5])
        return os.write(fd, report)
```

- [x] **Step 2: Add the autouse fixture to `tests/conftest.py`** — lines added only, no existing line changed. Insert `from pathlib import Path` above `from typing import Any`; replace the line `from custom_components.blinkybeacon.const import DOMAIN` with the block below (the `DOMAIN` import line itself stays as it is):

```python
from custom_components.blinkybeacon import usb_beacon
from custom_components.blinkybeacon.const import DOMAIN

from .fake_usb import FakeUsb
```

and append at the end of the file:

```python


@pytest.fixture(autouse=True)
def fake_usb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeUsb:
    """Point the USB code at a fake sysfs and /dev, empty until a test plugs in."""
    fake = FakeUsb(tmp_path / "usb")
    monkeypatch.setattr(usb_beacon, "SYSFS_ROOT", fake.sysfs)
    monkeypatch.setattr(usb_beacon, "DEV_ROOT", fake.dev)
    return fake
```

- [x] **Step 3: Write the failing tests.** Create `tests/test_usb_find.py`:

```python
"""Tests for finding beacons in USB ports, and the reports they take."""

from __future__ import annotations

import pytest

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
    uevent.write_text(uevent.read_text().replace("0000340D", "0000340d"))

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
```

- [x] **Step 4: Run them; expect the red state below.**

Run: `(cd "$BB" && timeout 300 .venv/bin/pytest -q -p no:cacheprovider tests/test_usb_find.py)`

Expected (recorded in the assembly): the conftest cannot import the module that does not exist yet, so nothing is collected:

```text
ImportError while loading conftest '$BB/tests/conftest.py'.
tests/conftest.py:12: in <module>
    from custom_components.blinkybeacon import usb_beacon
E   ImportError: cannot import name 'usb_beacon' from 'custom_components.blinkybeacon' ($BB/custom_components/blinkybeacon/__init__.py)
```

- [x] **Step 5: Write `custom_components/blinkybeacon/usb_beacon.py`:**

```python
"""Beacons plugged into this machine's USB ports, driven without a tray.

The beacon is a HID device that takes three fixed 10-byte output reports. It
falls idle unless its report is written again every few seconds, and a write
that fails is how an unplugged beacon shows.
"""

from __future__ import annotations

import os
from pathlib import Path
import re

from .const import STATE_FLASH, STATE_IDLE, STATE_SPIN

SYSFS_ROOT = Path("/sys")
DEV_ROOT = Path("/dev")

BEACON_HID_ID = "0003:0000340D:00001710"

REPORTS: dict[str, bytes] = {
    STATE_SPIN: bytes.fromhex("00 FF 01 66 C8 FF AD 52 81 D6"),
    STATE_FLASH: bytes.fromhex("00 FF 07 FF 50 FF 1C 8E B0 B8"),
    STATE_IDLE: bytes.fromhex("00 FF 00 00 64 00 32 9E D7 0D"),
}

_USB_PORT = re.compile(r"\d+-\d+(?:\.\d+)*")


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
    sysfs_root: Path | None = None, dev_root: Path | None = None
) -> dict[str, str]:
    """Map every USB port holding a beacon to its device file.

    Anything that cannot be read is skipped. This reads files: run it in the
    executor.
    """
    sysfs = SYSFS_ROOT if sysfs_root is None else sysfs_root
    dev = DEV_ROOT if dev_root is None else dev_root
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
        except OSError:
            continue
        if _hid_id(uevent) != BEACON_HID_ID:
            continue
        if (port := usb_port(path)) is not None:
            found.setdefault(port, str(dev / node))
    return found


def _hid_id(uevent: str) -> str | None:
    for line in uevent.splitlines():
        key, _, value = line.partition("=")
        if key == "HID_ID":
            return value.strip().upper()
    return None
```

- [x] **Step 6: Run the whole suite, lint and format; expect green.**

Run: `(cd "$BB" && timeout 300 .venv/bin/pytest -q -p no:cacheprovider && .venv/bin/ruff check custom_components tests && .venv/bin/ruff format --check custom_components tests)`

Expected: `88 passed in 3.88s`, `All checks passed!`, all files already formatted.

- [x] **Step 7: Read-only smoke on this machine's real `/sys`** (reads files only; opens no device; prints `{}` where no beacon is plugged in, and must not raise):

Run: `(cd "$BB" && .venv/bin/python -c "from custom_components.blinkybeacon.usb_beacon import find_beacons; print(find_beacons())")`

Expected: a dict, no exception. On this WSL machine it prints `{}`: it has no `/sys/class/hidraw` at all (checked while the plan was assembled). Record the output in the retro.

- [x] **Step 8: Commit and push.**

```bash
F="blinkybeacon-hassio/custom_components/blinkybeacon/usb_beacon.py blinkybeacon-hassio/tests/fake_usb.py blinkybeacon-hassio/tests/test_usb_find.py blinkybeacon-hassio/tests/conftest.py"
(cd "$W" && command grep -c -i -F -f "$NAMES_LIST" $F)   # 0 for each file
git -C "$W" diff main -- blinkybeacon-hassio/tests/conftest.py | command grep -c '^-[^-]'   # 0
git -C "$W" add $F
git -C "$W" commit -m "blinkybeacon-hassio: find beacons in USB ports by reading sysfs, and the three reports they take" -- $F
git -C "$W" branch --show-current   # wt/blinkybeacon-usb
git -C "$W" log --format=%B main..wt/blinkybeacon-usb | command grep -c -i -F -f "$NAMES_LIST"   # 0
git -C "$W" log -p main..wt/blinkybeacon-usb | command grep -c -F -f "$SECRETS_LIST"   # 0
git -C "$W" push origin wt/blinkybeacon-usb
```

### Task 2: Drive one beacon in a USB port

**Files:**
- Modify: `custom_components/blinkybeacon/usb_beacon.py` (replaced whole by the version below: the Task 1 part plus imports, `_LOGGER`, `_write_report` and `class UsbBeacon`), `custom_components/blinkybeacon/const.py`, `tests/conftest.py` (one line added)
- Create: `tests/test_usb_beacon.py`

**Interfaces:**
- Consumes: `find_beacons`, `REPORTS` (Task 1); `BeaconStatus`, `BlinkyBeaconNotConnectedError` (`api.py`); `FakeUsb`, `tick` (Task 1).
- Produces (`const.py`): `KEEPALIVE_INTERVAL = timedelta(seconds=5)`.
- Produces (`usb_beacon.py`): `_write_report` (module attribute, `os.write`); `class UsbBeacon(hass: HomeAssistant, port: str)` with attribute `port`, `async async_start() -> None` (writes stop, then a keepalive every `KEEPALIVE_INTERVAL` with `cancel_on_shutdown=True`), `async async_close() -> None` (ends the keepalive, writes stop if the device is open, closes, refuses every later write), `async status() -> BeaconStatus` (mode, and connected = the port holds a beacon and the device is open), `async spin()`, `async flash()`, `async stop() -> BeaconStatus` (raise `BlinkyBeaconNotConnectedError` when the report was not taken), and the keepalive callback `async _async_keepalive(now: datetime) -> None`.
- Payload checklist: each report is exactly 10 bytes with report ID `0x00` first (pinned in Task 1); a write counts only when `_write_report` returns 10; any `OSError` or short write closes the device, sets the mode idle and logs one warning per new error kind, by type and port, never system text; a missing port is not an error and logs nothing.

- [x] **Step 1: Route writes through the fake.** In `tests/conftest.py`'s `fake_usb` fixture, add this line after the `DEV_ROOT` line (lines added only):

```python
    monkeypatch.setattr(usb_beacon, "_write_report", fake.write)
```

- [x] **Step 2: Write the failing tests.** Create `tests/test_usb_beacon.py`:

```python
"""Tests for driving a beacon in a USB port."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
import errno
import logging

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
```

- [x] **Step 3: Run them; expect the red state below.**

Run: `(cd "$BB" && timeout 300 .venv/bin/pytest -q -p no:cacheprovider tests/test_usb_beacon.py)`, then one 0.1.0 file, `(cd "$BB" && timeout 300 .venv/bin/pytest -q -p no:cacheprovider tests/test_init.py)`

Expected (recorded): the new file cannot import `UsbBeacon`, so collection stops; and every other test errors in the autouse fixture, because the module has no `_write_report` yet. Both clear in Step 5:

```text
Hint: make sure your test modules/packages have valid Python names.
Traceback:
~/.local/share/uv/python/cpython-3.14.10-linux-x86_64-gnu/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_usb_beacon.py:20: in <module>
    from custom_components.blinkybeacon.usb_beacon import UsbBeacon
E   ImportError: cannot import name 'UsbBeacon' from 'custom_components.blinkybeacon.usb_beacon' ($BB/custom_components/blinkybeacon/usb_beacon.py)
=========================== short test summary info ============================
ERROR tests/test_usb_beacon.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.22s
…
=========================== short test summary info ============================
ERROR tests/test_init.py::test_setup_and_unload - AttributeError: <module 'cu...
ERROR tests/test_init.py::test_setup_retries_when_tray_down - AttributeError:...
ERROR tests/test_init.py::test_device_registered - AttributeError: <module 'c...
3 errors in 0.43s
```

- [x] **Step 4: Add the keepalive interval.** In `custom_components/blinkybeacon/const.py`, after `MAX_DURATION = 3600`, add:

```python

KEEPALIVE_INTERVAL = timedelta(seconds=5)
```

- [x] **Step 5: Replace `custom_components/blinkybeacon/usb_beacon.py` with:**

```python
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
    sysfs_root: Path | None = None, dev_root: Path | None = None
) -> dict[str, str]:
    """Map every USB port holding a beacon to its device file.

    Anything that cannot be read is skipped. This reads files: run it in the
    executor.
    """
    sysfs = SYSFS_ROOT if sysfs_root is None else sysfs_root
    dev = DEV_ROOT if dev_root is None else dev_root
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
        except OSError:
            continue
        if _hid_id(uevent) != BEACON_HID_ID:
            continue
        if (port := usb_port(path)) is not None:
            found.setdefault(port, str(dev / node))
    return found


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
        self._fd: int | None = None
        self._mode = STATE_IDLE
        self._closed = False
        self._last_error: str | None = None
        self._cancel_keepalive: CALLBACK_TYPE | None = None

    async def async_start(self) -> None:
        """Set the beacon idle, then keep writing its mode."""
        await self._async_write(STATE_IDLE)
        self._cancel_keepalive = async_track_time_interval(
            self._hass,
            self._async_keepalive,
            KEEPALIVE_INTERVAL,
            name=f"BlinkyBeacon USB port {self.port}",
            cancel_on_shutdown=True,
        )

    async def async_close(self) -> None:
        """Stop the keepalive, stop the beacon if it is there, and close it."""
        if self._cancel_keepalive is not None:
            self._cancel_keepalive()
            self._cancel_keepalive = None
        async with self._lock:
            self._closed = True
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
        """Write a mode's report, or the current mode's; False if not taken."""
        async with self._lock:
            if self._closed:
                return False
            mode = self._mode if mode is None else mode
            if await self._hass.async_add_executor_job(self._write, REPORTS[mode]):
                self._mode = mode
                return True
            self._mode = STATE_IDLE
            return False

    def _write(self, report: bytes) -> bool:
        """Write one report, opening the device first if it is closed."""
        try:
            if self._fd is None:
                if (path := find_beacons().get(self.port)) is None:
                    return False
                self._fd = os.open(path, os.O_WRONLY | os.O_CLOEXEC)
            written = _write_report(self._fd, report)
        except OSError as err:
            self._failed(type(err).__name__)
            return False
        if written != len(report):
            self._failed("short write")
            return False
        self._last_error = None
        return True

    def _stop_and_close(self) -> None:
        if self._fd is not None:
            try:
                _write_report(self._fd, REPORTS[STATE_IDLE])
            except OSError as err:
                self._failed(type(err).__name__)
        self._close()

    def _failed(self, kind: str) -> None:
        self._close()
        if kind != self._last_error:
            self._last_error = kind
            _LOGGER.warning(
                "The beacon on USB port %s did not take a report (%s)", self.port, kind
            )

    def _close(self) -> None:
        if self._fd is not None:
            with suppress(OSError):
                os.close(self._fd)
            self._fd = None
```

- [x] **Step 6: Run the whole suite, lint and format; expect green.**

Run: `(cd "$BB" && timeout 300 .venv/bin/pytest -q -p no:cacheprovider && .venv/bin/ruff check custom_components tests && .venv/bin/ruff format --check custom_components tests)`

Expected: `100 passed in 5.35s`, `All checks passed!`, all files already formatted.

- [x] **Step 7: Prove the two race tests guard their bugs** (then restore the file). Change line `await self._async_write()` in `_async_keepalive` to `await self._async_write(self._mode)`: `test_keepalive_never_writes_an_older_mode` must fail. Restore it, then delete the two lines `if self._closed:` / `return False` in `_async_write`: `test_keepalive_queued_behind_close_does_not_reopen` and `test_close_stops_the_beacon_and_the_keepalive` must fail. Restore, and confirm `git -C "$W" diff --stat` shows only this task's files. (Recorded in the assembly: `1 failed, 11 passed` and `2 failed, 10 passed`.)

- [x] **Step 8: Commit and push.**

```bash
F="blinkybeacon-hassio/custom_components/blinkybeacon/usb_beacon.py blinkybeacon-hassio/custom_components/blinkybeacon/const.py blinkybeacon-hassio/tests/test_usb_beacon.py blinkybeacon-hassio/tests/conftest.py"
(cd "$W" && command grep -c -i -F -f "$NAMES_LIST" $F)   # 0 for each file
git -C "$W" diff main -- blinkybeacon-hassio/tests/conftest.py | command grep -c '^-[^-]'   # 0
git -C "$W" add $F
git -C "$W" commit -m "blinkybeacon-hassio: drive a beacon in a USB port: its reports written in the executor, again every 5 seconds, and not connected from a failed write or an empty port until it is back" -- $F
git -C "$W" branch --show-current   # wt/blinkybeacon-usb
git -C "$W" log --format=%B main..wt/blinkybeacon-usb | command grep -c -i -F -f "$NAMES_LIST"   # 0
git -C "$W" log -p main..wt/blinkybeacon-usb | command grep -c -F -f "$SECRETS_LIST"   # 0
git -C "$W" push origin wt/blinkybeacon-usb
```

### Task 3: A USB beacon as a device, with its light, sensor and actions

**Files:**
- Modify: `custom_components/blinkybeacon/const.py`, `custom_components/blinkybeacon/__init__.py`, `custom_components/blinkybeacon/coordinator.py`, `custom_components/blinkybeacon/entity.py`, `custom_components/blinkybeacon/strings.json`, `custom_components/blinkybeacon/translations/en.json`, `tests/conftest.py` (lines added only)
- Create: `tests/test_usb_entry.py`

**Interfaces:**
- Consumes: `UsbBeacon` (Task 2); `FakeUsb`, `tick`, `SPIN`, `FLASH`, `STOP` (Task 1).
- Produces (`const.py`): `CONF_USB_PORT = "usb_port"`.
- Produces (`coordinator.py`): `BlinkyBeaconCoordinator(hass, entry, client: BlinkyBeaconClient | UsbBeacon)`; `address` gives `"USB port <port>"` for a USB entry; `USB_ERRORS = {"cannot_reach": "usb_not_loaded", "not_plugged_in": "usb_not_plugged_in"}`; `beacon_error(entry, key)` gives, for a USB entry, `HomeAssistantError(translation_key=USB_ERRORS[key], translation_placeholders={"name": title, "port": port})`.
- Produces (`__init__.py`): an entry with `usb_port` in its data gets a `UsbBeacon`, started before the first refresh, closed on unload (`entry.async_on_unload(client.async_close)`); a USB entry loads whether or not its beacon is plugged in.
- Produces (`tests/conftest.py`): fixture `usb_entry -> MockConfigEntry` (title `"Team A beacon"`, data `{"usb_port": "1-1"}`, unique id `"usb:1-1"`).

- [x] **Step 1: Add the `usb_entry` fixture.** Append to `tests/conftest.py`:

```python


@pytest.fixture
def usb_entry() -> MockConfigEntry:
    """A config entry for team A's beacon, on USB port 1-1."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Team A beacon",
        data={"usb_port": "1-1"},
        unique_id="usb:1-1",
    )
```

- [x] **Step 2: Write the failing tests.** Create `tests/test_usb_entry.py`:

```python
"""Tests for a beacon plugged into Home Assistant: its device, entities, actions."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryDisabler, ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.blinkybeacon.const import DOMAIN

from .conftest import BASE, setup_integration, status_json
from .fake_usb import FLASH, SPIN, STOP, FakeUsb, tick

LIGHT = "light.team_a_beacon"
SENSOR = "binary_sensor.team_a_beacon_usb_connected"


def _device_id(device_registry: dr.DeviceRegistry, entry: MockConfigEntry) -> str:
    return dr.async_entries_for_config_entry(device_registry, entry.entry_id)[0].id


async def _call(hass: HomeAssistant, service: str, **data: object) -> None:
    await hass.services.async_call(DOMAIN, service, data, blocking=True)


async def test_setup_and_unload(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    usb_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A plugged-in beacon loads idle; unloading stops it and ends the keepalive."""
    fake_usb.plug("1-1")

    await setup_integration(hass, usb_entry)

    assert usb_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(LIGHT).state == STATE_OFF
    assert hass.states.get(SENSOR).state == STATE_ON
    assert fake_usb.written() == [STOP]

    assert await hass.config_entries.async_unload(usb_entry.entry_id)
    await tick(hass, freezer, 10)

    assert usb_entry.state is ConfigEntryState.NOT_LOADED
    assert fake_usb.written() == [STOP, STOP]


async def test_missing_at_setup_loads_unavailable(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    usb_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A beacon not plugged in at startup still loads, shown missing until it is."""
    await setup_integration(hass, usb_entry)

    assert usb_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(LIGHT).state == STATE_UNAVAILABLE
    assert hass.states.get(SENSOR).state == STATE_OFF

    fake_usb.plug("1-1")
    await tick(hass, freezer, 5)
    await tick(hass, freezer, 5)

    assert hass.states.get(LIGHT).state == STATE_OFF
    assert hass.states.get(SENSOR).state == STATE_ON


async def test_unplug_and_replug(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    usb_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Unplugged, the light is unavailable; plugged back, it returns idle."""
    fake_usb.plug("1-1", "hidraw0")
    await setup_integration(hass, usb_entry)
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": LIGHT}, blocking=True
    )

    fake_usb.unplug("hidraw0")
    await tick(hass, freezer, 5)

    assert hass.states.get(LIGHT).state == STATE_UNAVAILABLE
    assert hass.states.get(SENSOR).state == STATE_OFF

    fake_usb.plug("1-1", "hidraw1")
    await tick(hass, freezer, 5)
    await tick(hass, freezer, 5)

    assert hass.states.get(LIGHT).state == STATE_OFF
    assert hass.states.get(SENSOR).state == STATE_ON
    assert fake_usb.written("hidraw1")[0] == STOP


async def test_light_turn_on_spins(
    hass: HomeAssistant, fake_usb: FakeUsb, usb_entry: MockConfigEntry
) -> None:
    """Turning the light on spins the beacon, and the state follows at once."""
    fake_usb.plug("1-1")
    await setup_integration(hass, usb_entry)

    await hass.services.async_call(
        "light", "turn_on", {"entity_id": LIGHT}, blocking=True
    )

    assert fake_usb.written() == [STOP, SPIN]
    light = hass.states.get(LIGHT)
    assert (light.state, light.attributes["effect"]) == (STATE_ON, "spin")


async def test_actions_and_duration(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    usb_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Spin, flash and stop drive the beacon; a duration stops it on time."""
    fake_usb.plug("1-1")
    await setup_integration(hass, usb_entry)
    device = _device_id(device_registry, usb_entry)

    await _call(hass, "flash", device_id=device)
    await _call(hass, "stop", device_id=device)
    assert fake_usb.written() == [STOP, FLASH, STOP]

    await _call(hass, "spin", device_id=device, duration=10)
    await tick(hass, freezer, 9)
    assert fake_usb.written()[-1] == SPIN
    assert hass.states.get(LIGHT).state == STATE_ON

    await tick(hass, freezer, 1)
    assert fake_usb.written()[-1] == STOP
    assert hass.states.get(LIGHT).state == STATE_OFF


async def test_action_on_missing_beacon_names_it(
    hass: HomeAssistant,
    usb_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """An action on a beacon that is not plugged in fails, naming it and its port."""
    await setup_integration(hass, usb_entry)

    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, "spin", device_id=_device_id(device_registry, usb_entry))

    assert err.value.translation_key == "usb_not_plugged_in"
    assert err.value.translation_placeholders == {
        "name": "Team A beacon",
        "port": "1-1",
    }
    assert str(err.value) == "Team A beacon is not plugged into USB port 1-1"


async def test_action_on_not_loaded_beacon_names_it(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    device_registry: dr.DeviceRegistry,
) -> None:
    """A USB beacon whose entry is not loaded fails the action, never skips it."""
    fake_usb.plug("1-1")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Team A beacon",
        data={"usb_port": "1-1"},
        unique_id="usb:1-1",
        disabled_by=ConfigEntryDisabler.USER,
    )
    entry.add_to_hass(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, entry.entry_id)}
    )
    assert await async_setup_component(hass, DOMAIN, {})

    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, "spin", device_id=device.id)

    assert err.value.translation_key == "usb_not_loaded"
    assert err.value.translation_placeholders == {
        "name": "Team A beacon",
        "port": "1-1",
    }
    assert fake_usb.written() == []


async def test_device_registered(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    usb_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """A USB beacon is a device named as given, with no tray settings page."""
    fake_usb.plug("1-1")
    await setup_integration(hass, usb_entry)

    devices = dr.async_entries_for_config_entry(device_registry, usb_entry.entry_id)
    assert len(devices) == 1
    assert devices[0].name == "Team A beacon"
    assert devices[0].model == "USB beacon"
    assert devices[0].configuration_url is None


async def test_tray_and_usb_beacons_together(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    usb_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """One action reaches a tray and a USB beacon; the error names the one missing."""
    aioclient_mock.get(f"{BASE}/status", json=status_json())
    aioclient_mock.post(f"{BASE}/spin", json=status_json("spin"))
    await setup_integration(hass, mock_config_entry)
    await setup_integration(hass, usb_entry)

    with pytest.raises(HomeAssistantError) as err:
        await _call(
            hass,
            "spin",
            device_id=[
                _device_id(device_registry, mock_config_entry),
                _device_id(device_registry, usb_entry),
            ],
        )

    assert err.value.translation_key == "commands_failed"
    assert err.value.translation_placeholders == {"names": "Team A beacon"}
    assert hass.states.get("light.home_beacon").attributes["effect"] == "spin"
```

- [x] **Step 3: Run them; expect the red state below.**

Run: `(cd "$BB" && timeout 300 .venv/bin/pytest -q -p no:cacheprovider tests/test_usb_entry.py)`

Expected (recorded): setting up a USB entry fails on the missing `host` key, so the entities never appear and the errors are the tray's:

```text
=========================== short test summary info ============================
FAILED tests/test_usb_entry.py::test_setup_and_unload - AssertionError: asser...
FAILED tests/test_usb_entry.py::test_missing_at_setup_loads_unavailable - Ass...
FAILED tests/test_usb_entry.py::test_unplug_and_replug - homeassistant.except...
FAILED tests/test_usb_entry.py::test_light_turn_on_spins - homeassistant.exce...
FAILED tests/test_usb_entry.py::test_actions_and_duration - IndexError: list ...
FAILED tests/test_usb_entry.py::test_action_on_missing_beacon_names_it - Inde...
FAILED tests/test_usb_entry.py::test_action_on_not_loaded_beacon_names_it - K...
FAILED tests/test_usb_entry.py::test_device_registered - assert 0 == 1
FAILED tests/test_usb_entry.py::test_tray_and_usb_beacons_together - IndexErr...
9 failed in 0.86s
```

- [x] **Step 4: Add the data key.** In `custom_components/blinkybeacon/const.py`, after `MAX_DURATION = 3600` and its blank line, add `CONF_USB_PORT = "usb_port"` so the end of the file reads:

```python
MIN_DURATION = 1
MAX_DURATION = 3600

CONF_USB_PORT = "usb_port"
KEEPALIVE_INTERVAL = timedelta(seconds=5)
```

- [x] **Step 5: Replace `custom_components/blinkybeacon/__init__.py` with:**

```python
"""The BlinkyBeacon integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import BlinkyBeaconClient
from .const import CONF_USB_PORT, DOMAIN
from .coordinator import BlinkyBeaconConfigEntry, BlinkyBeaconCoordinator
from .services import async_setup_services
from .usb_beacon import UsbBeacon

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.LIGHT]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions once, for every beacon."""
    async_setup_services(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: BlinkyBeaconConfigEntry
) -> bool:
    """Set up a beacon; retried later if its tray does not answer."""
    client: BlinkyBeaconClient | UsbBeacon
    if (usb_port := entry.data.get(CONF_USB_PORT)) is not None:
        client = UsbBeacon(hass, usb_port)
        await client.async_start()
        entry.async_on_unload(client.async_close)
    else:
        client = BlinkyBeaconClient(
            async_get_clientsession(hass), entry.data[CONF_HOST], entry.data[CONF_PORT]
        )
    coordinator = BlinkyBeaconCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    async def _async_on_stop(_event: Event) -> None:
        # HA does not unload entries when it shuts down.
        await coordinator.async_shutdown_stop()

    entry.async_on_unload(
        hass.bus.async_listen(EVENT_HOMEASSISTANT_STOP, _async_on_stop)
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: BlinkyBeaconConfigEntry
) -> bool:
    """Unload a beacon, first sending any pending timed stop."""
    await entry.runtime_data.async_shutdown_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
```

- [x] **Step 6: Replace `custom_components/blinkybeacon/coordinator.py` with:**

```python
"""Polls one beacon for its state and sends it commands."""

from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    BeaconStatus,
    BlinkyBeaconClient,
    BlinkyBeaconConnectionError,
    BlinkyBeaconError,
    BlinkyBeaconNotConnectedError,
)
from .const import CONF_USB_PORT, DOMAIN, SCAN_INTERVAL
from .usb_beacon import UsbBeacon

_LOGGER = logging.getLogger(__name__)

type BlinkyBeaconConfigEntry = ConfigEntry[BlinkyBeaconCoordinator]

USB_ERRORS = {"cannot_reach": "usb_not_loaded", "not_plugged_in": "usb_not_plugged_in"}


class BlinkyBeaconCoordinator(DataUpdateCoordinator[BeaconStatus]):
    """Holds one beacon's last known state."""

    config_entry: BlinkyBeaconConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: BlinkyBeaconConfigEntry,
        client: BlinkyBeaconClient | UsbBeacon,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=SCAN_INTERVAL,
            always_update=False,
        )
        self.client = client
        self._cancel_timed_stop: CALLBACK_TYPE | None = None

    @property
    def address(self) -> str:
        """The tray's host:port, or the beacon's USB port, for messages."""
        data = self.config_entry.data
        if (usb_port := data.get(CONF_USB_PORT)) is not None:
            return f"USB port {usb_port}"
        return f"{data[CONF_HOST]}:{data[CONF_PORT]}"

    async def _async_update_data(self) -> BeaconStatus:
        try:
            return await self.client.status()
        except BlinkyBeaconError as err:
            raise UpdateFailed(
                f"{self.address} did not answer /status: {err!r}"
            ) from err

    async def async_command(self, command: str, duration: int | None = None) -> None:
        """Send spin, flash or stop; raise an error naming the beacon if it fails.

        A command that succeeds replaces any pending timed stop; one that fails
        leaves it in place. With a duration, a stop follows that many seconds later.
        """
        try:
            status = await getattr(self.client, command)()
        except BlinkyBeaconConnectionError as err:
            raise self.error("cannot_reach") from err
        except BlinkyBeaconNotConnectedError as err:
            await self.async_request_refresh()
            raise self.error("not_plugged_in") from err
        except BlinkyBeaconError as err:
            raise self.error("unexpected_reply") from err
        self._async_cancel_timed_stop()
        self.async_set_updated_data(status)
        if duration:
            self._cancel_timed_stop = async_call_later(
                self.hass, duration, self._async_timed_stop
            )

    async def async_shutdown_stop(self) -> None:
        """Send a pending timed stop now, so a timed spin never outlives HA."""
        if self._cancel_timed_stop is None:
            return
        self._async_cancel_timed_stop()
        await self._async_stop_or_warn()

    @callback
    def _async_cancel_timed_stop(self) -> None:
        if self._cancel_timed_stop is not None:
            self._cancel_timed_stop()
            self._cancel_timed_stop = None

    async def _async_timed_stop(self, _now: datetime) -> None:
        self._cancel_timed_stop = None
        await self._async_stop_or_warn()

    async def _async_stop_or_warn(self) -> None:
        try:
            await self.async_command("stop")
        except HomeAssistantError as err:
            _LOGGER.warning(
                "Could not stop %s at the end of its timed command: %s",
                self.config_entry.title,
                err,
            )

    def error(self, key: str) -> HomeAssistantError:
        """A translated error about this beacon."""
        return beacon_error(self.config_entry, key)


def beacon_error(entry: ConfigEntry, key: str) -> HomeAssistantError:
    """A translated error naming a beacon and where it is plugged in."""
    if (usb_port := entry.data.get(CONF_USB_PORT)) is not None:
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=USB_ERRORS[key],
            translation_placeholders={"name": entry.title, "port": usb_port},
        )
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders={
            "name": entry.title,
            "address": f"{entry.data[CONF_HOST]}:{entry.data[CONF_PORT]}",
        },
    )
```

- [x] **Step 7: Replace `custom_components/blinkybeacon/entity.py` with:**

```python
"""The base entity shared by a beacon's light and sensor."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import BlinkyBeaconClient
from .const import DOMAIN
from .coordinator import BlinkyBeaconCoordinator


class BlinkyBeaconEntity(CoordinatorEntity[BlinkyBeaconCoordinator]):
    """An entity of one beacon's device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BlinkyBeaconCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        if isinstance(client := coordinator.client, BlinkyBeaconClient):
            model, url = "blinkybeacon-tray", f"{client.base_url}/settings"
        else:
            model, url = "USB beacon", None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="BlinkyBeacon",
            model=model,
            configuration_url=url,
        )
```

- [x] **Step 8: Add the two errors** to `custom_components/blinkybeacon/strings.json`. Replace

```json
    "unknown_effect": {
      "message": "A beacon has no effect called {effect}. Use one of: {effects}."
    }
  },
```

with

```json
    "unknown_effect": {
      "message": "A beacon has no effect called {effect}. Use one of: {effects}."
    },
    "usb_not_plugged_in": {
      "message": "{name} is not plugged into USB port {port}."
    },
    "usb_not_loaded": {
      "message": "{name} on USB port {port} is not loaded. Check its entry under Settings > Devices & services."
    }
  },
```

then `cp custom_components/blinkybeacon/strings.json custom_components/blinkybeacon/translations/en.json` (from `$BB`) and check `cmp` is silent.

- [x] **Step 9: Run the whole suite, lint and format; expect green.**

Run: `(cd "$BB" && timeout 300 .venv/bin/pytest -q -p no:cacheprovider && .venv/bin/ruff check custom_components tests && .venv/bin/ruff format --check custom_components tests && cmp custom_components/blinkybeacon/strings.json custom_components/blinkybeacon/translations/en.json)`

Expected: `109 passed in 5.40s`, `All checks passed!`, all files already formatted, `cmp` silent.

- [x] **Step 10: Commit and push.**

```bash
P=blinkybeacon-hassio/custom_components/blinkybeacon
F="$P/const.py $P/__init__.py $P/coordinator.py $P/entity.py $P/strings.json $P/translations/en.json blinkybeacon-hassio/tests/test_usb_entry.py blinkybeacon-hassio/tests/conftest.py"
(cd "$W" && command grep -c -i -F -f "$NAMES_LIST" $F)   # 0 for each file
git -C "$W" diff main -- blinkybeacon-hassio/tests/conftest.py | command grep -c '^-[^-]'   # 0
git -C "$W" add $F
git -C "$W" commit -m "blinkybeacon-hassio: a beacon plugged into Home Assistant is a device with the same light, sensor and actions as a tray beacon, its errors naming it and its USB port" -- $F
git -C "$W" branch --show-current   # wt/blinkybeacon-usb
git -C "$W" log --format=%B main..wt/blinkybeacon-usb | command grep -c -i -F -f "$NAMES_LIST"   # 0
git -C "$W" log -p main..wt/blinkybeacon-usb | command grep -c -F -f "$SECRETS_LIST"   # 0
git -C "$W" push origin wt/blinkybeacon-usb
```

### Task 4: The notice while a USB beacon is missing, and its fix

**Files:**
- Create: `custom_components/blinkybeacon/repairs.py`, `tests/test_repairs.py`
- Modify: `custom_components/blinkybeacon/__init__.py`, `custom_components/blinkybeacon/strings.json`, `custom_components/blinkybeacon/translations/en.json`

**Interfaces:**
- Consumes: `BlinkyBeaconCoordinator` with `data.connected` (Task 3); `CONF_USB_PORT`.
- Produces (`repairs.py`): `ISSUE_USB_MISSING = "usb_missing"`, `missing_issue_id(entry_id) -> str` (`"usb_missing_<entry_id>"`), `async_track_missing(hass, coordinator) -> None` (callback; raises the fixable warning while `data.connected` is false, deletes it when true and on unload), `RemoveMissingBeaconFlow(entry_id)`, `async_create_fix_flow(hass, issue_id, data) -> RepairsFlow`. The issue's data is `{"entry_id": …}`, placeholders `{"name", "port"}`. `homeassistant.components.repairs` is imported without a manifest dependency, as core integrations with a `repairs.py` do (for example `backblaze_b2`).

- [x] **Step 1: Write the failing tests.** Create `tests/test_repairs.py`:

```python
"""Tests for the notice that a USB beacon is missing, and its fix."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.blinkybeacon.const import DOMAIN

from .conftest import BASE, setup_integration, status_json
from .fake_usb import FakeUsb, tick


def _issue(hass: HomeAssistant, entry: MockConfigEntry) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, f"usb_missing_{entry.entry_id}")


async def test_raised_when_the_port_empties_and_cleared_on_return(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    usb_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The notice names the beacon and its port, and clears once it is back."""
    fake_usb.plug("1-1")
    await setup_integration(hass, usb_entry)
    assert _issue(hass, usb_entry) is None

    fake_usb.unplug()
    await tick(hass, freezer, 5)

    issue = _issue(hass, usb_entry)
    assert issue is not None
    assert issue.translation_key == "usb_missing"
    assert issue.translation_placeholders == {"name": "Team A beacon", "port": "1-1"}
    assert issue.is_fixable
    assert issue.severity is ir.IssueSeverity.WARNING

    fake_usb.plug("1-1")
    await tick(hass, freezer, 5)
    await tick(hass, freezer, 5)

    assert _issue(hass, usb_entry) is None


async def test_raised_at_startup_when_missing(
    hass: HomeAssistant, usb_entry: MockConfigEntry
) -> None:
    """A beacon missing when Home Assistant starts has its notice at once."""
    await setup_integration(hass, usb_entry)

    assert _issue(hass, usb_entry) is not None


async def test_fix_removes_the_beacon(
    hass: HomeAssistant,
    usb_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Confirming the fix removes the beacon's entry and device, and the notice."""
    await setup_integration(hass, usb_entry)
    assert await async_setup_component(hass, "repairs", {})
    flows = repairs_flow_manager(hass)

    result = await flows.async_init(
        DOMAIN, context={"issue_id": f"usb_missing_{usb_entry.entry_id}"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"] == {
        "name": "Team A beacon",
        "port": "1-1",
    }

    result = await flows.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert hass.config_entries.async_get_entry(usb_entry.entry_id) is None
    assert not dr.async_entries_for_config_entry(device_registry, usb_entry.entry_id)
    assert _issue(hass, usb_entry) is None


async def test_cleared_on_unload(
    hass: HomeAssistant, usb_entry: MockConfigEntry
) -> None:
    """An unloaded beacon carries no notice; it is raised again if still missing."""
    await setup_integration(hass, usb_entry)

    assert await hass.config_entries.async_unload(usb_entry.entry_id)
    assert _issue(hass, usb_entry) is None

    assert await hass.config_entries.async_setup(usb_entry.entry_id)
    assert _issue(hass, usb_entry) is not None


async def test_tray_never_raises_it(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A tray whose light is unplugged shows it on its sensor, with no notice."""
    aioclient_mock.get(f"{BASE}/status", json=status_json(connected=False))

    await setup_integration(hass, mock_config_entry)

    assert not [
        issue
        for (domain, _), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN
    ]
```

- [x] **Step 2: Run them; expect the red state below.**

Run: `(cd "$BB" && timeout 300 .venv/bin/pytest -q -p no:cacheprovider tests/test_repairs.py)`

Expected (recorded): no notice is ever raised, and the fix flow has no issue to start from. `test_tray_never_raises_it` already passes here, since it checks that nothing is raised for a tray:

```text
=========================== short test summary info ============================
FAILED tests/test_repairs.py::test_raised_when_the_port_empties_and_cleared_on_return
FAILED tests/test_repairs.py::test_raised_at_startup_when_missing - assert No...
FAILED tests/test_repairs.py::test_fix_removes_the_beacon - homeassistant.dat...
FAILED tests/test_repairs.py::test_cleared_on_unload - assert None is not None
4 failed, 1 passed in 0.76s
```

- [x] **Step 3: Create `custom_components/blinkybeacon/repairs.py`:**

```python
"""The notice that a USB beacon is missing from its port, and its fix."""

from __future__ import annotations

from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
import voluptuous as vol

from .const import CONF_USB_PORT, DOMAIN
from .coordinator import BlinkyBeaconCoordinator

ISSUE_USB_MISSING = "usb_missing"


def missing_issue_id(entry_id: str) -> str:
    """The ID of the notice that an entry's beacon is missing."""
    return f"{ISSUE_USB_MISSING}_{entry_id}"


@callback
def async_track_missing(
    hass: HomeAssistant, coordinator: BlinkyBeaconCoordinator
) -> None:
    """Keep the notice raised while the beacon is missing, until it is unloaded."""
    entry = coordinator.config_entry
    issue_id = missing_issue_id(entry.entry_id)

    @callback
    def _async_update() -> None:
        if coordinator.data.connected:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
            return
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            data={"entry_id": entry.entry_id},
            is_fixable=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_USB_MISSING,
            translation_placeholders={
                "name": entry.title,
                "port": entry.data[CONF_USB_PORT],
            },
        )

    _async_update()
    entry.async_on_unload(coordinator.async_add_listener(_async_update))
    entry.async_on_unload(lambda: ir.async_delete_issue(hass, DOMAIN, issue_id))


class RemoveMissingBeaconFlow(RepairsFlow):
    """Removes a missing beacon once the user confirms it is not coming back."""

    def __init__(self, entry_id: str) -> None:
        self._entry_id = entry_id

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Ask before removing."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Remove the beacon's entry, with its device and entities."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_create_entry(data={})
        if user_input is not None:
            await self.hass.config_entries.async_remove(entry.entry_id)
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "name": entry.title,
                "port": entry.data[CONF_USB_PORT],
            },
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """The fix for a missing beacon: remove it."""
    return RemoveMissingBeaconFlow(str(data["entry_id"]) if data else "")
```

- [x] **Step 4: Replace `custom_components/blinkybeacon/__init__.py` with:**

```python
"""The BlinkyBeacon integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import BlinkyBeaconClient
from .const import CONF_USB_PORT, DOMAIN
from .coordinator import BlinkyBeaconConfigEntry, BlinkyBeaconCoordinator
from .repairs import async_track_missing
from .services import async_setup_services
from .usb_beacon import UsbBeacon

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.LIGHT]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions once, for every beacon."""
    async_setup_services(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: BlinkyBeaconConfigEntry
) -> bool:
    """Set up a beacon; retried later if its tray does not answer."""
    client: BlinkyBeaconClient | UsbBeacon
    if (usb_port := entry.data.get(CONF_USB_PORT)) is not None:
        client = UsbBeacon(hass, usb_port)
        await client.async_start()
        entry.async_on_unload(client.async_close)
    else:
        client = BlinkyBeaconClient(
            async_get_clientsession(hass), entry.data[CONF_HOST], entry.data[CONF_PORT]
        )
    coordinator = BlinkyBeaconCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    async def _async_on_stop(_event: Event) -> None:
        # HA does not unload entries when it shuts down.
        await coordinator.async_shutdown_stop()

    entry.async_on_unload(
        hass.bus.async_listen(EVENT_HOMEASSISTANT_STOP, _async_on_stop)
    )
    if usb_port is not None:
        async_track_missing(hass, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: BlinkyBeaconConfigEntry
) -> bool:
    """Unload a beacon, first sending any pending timed stop."""
    await entry.runtime_data.async_shutdown_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
```

- [x] **Step 5: Add the notice's text** to `custom_components/blinkybeacon/strings.json`. Replace

```json
  "services": {
    "spin": {
```

with

```json
  "issues": {
    "usb_missing": {
      "title": "{name} is missing from USB port {port}",
      "fix_flow": {
        "step": {
          "confirm": {
            "title": "Remove {name}?",
            "description": "No beacon is plugged into USB port {port}, where {name} was. Plug it back into that port and this notice clears by itself.\n\nIf {name} is not coming back, submit to remove it with its device and entities. A beacon plugged into another port is offered as a new beacon."
          }
        }
      }
    }
  },
  "services": {
    "spin": {
```

then copy it to `translations/en.json` and check `cmp` is silent.

- [x] **Step 6: Run the whole suite, lint and format; expect green.**

Run: `(cd "$BB" && timeout 300 .venv/bin/pytest -q -p no:cacheprovider && .venv/bin/ruff check custom_components tests && .venv/bin/ruff format --check custom_components tests && cmp custom_components/blinkybeacon/strings.json custom_components/blinkybeacon/translations/en.json)`

Expected: `114 passed in 4.75s`, `All checks passed!`, all files already formatted, `cmp` silent.

- [x] **Step 7: Commit and push.**

```bash
P=blinkybeacon-hassio/custom_components/blinkybeacon
F="$P/repairs.py $P/__init__.py $P/strings.json $P/translations/en.json blinkybeacon-hassio/tests/test_repairs.py"
(cd "$W" && command grep -c -i -F -f "$NAMES_LIST" $F)   # 0 for each file
git -C "$W" add $F
git -C "$W" commit -m "blinkybeacon-hassio: a repair notice while a USB beacon is missing from its port, cleared when it is back; its fix removes the beacon" -- $F
git -C "$W" branch --show-current   # wt/blinkybeacon-usb
git -C "$W" log --format=%B main..wt/blinkybeacon-usb | command grep -c -i -F -f "$NAMES_LIST"   # 0
git -C "$W" log -p main..wt/blinkybeacon-usb | command grep -c -F -f "$SECRETS_LIST"   # 0
git -C "$W" push origin wt/blinkybeacon-usb
```

### Task 5: Add a USB beacon by hand, naming it while it flashes

**Files:**
- Modify: `custom_components/blinkybeacon/config_flow.py`, `custom_components/blinkybeacon/strings.json`, `custom_components/blinkybeacon/translations/en.json`
- Create: `tests/test_usb_config_flow.py`

**Interfaces:**
- Consumes: `UsbBeacon`, `find_beacons`, `usb_unique_id` (Tasks 1–2); `CONF_USB_PORT` (Task 3); entry setup for a USB entry (Task 3).
- Produces (`config_flow.py`): steps `user` (menu `["tray", "usb"]` when `_async_unnamed_ports()` is not empty, else the `tray` form), `tray` (the 0.1.0 form, unchanged logic), `usb` (field `usb_port`, `vol.In({port: "USB port <port>"})`; none → the `tray` form with error `no_usb_beacon`; a port gone since the list was shown → error `usb_beacon_gone`), `name` (field `name`, default `"Beacon on USB port <port>"`; flashes through a private `UsbBeacon` while shown; blank → error `name_required`; creates `title=<name stripped>`, `data={"usb_port": port}`, unique id `usb:<port>`), `reconfigure` (aborts `usb_not_reconfigurable` on a USB entry). `async_remove()` closes the flasher. Private `_async_unnamed_ports() -> list[str]` and `_async_stop_flashing()`. Task 6 adds the offer steps and relies on `self._usb_port` and `async_step_name`.

- [x] **Step 1: Write the failing tests.** Create `tests/test_usb_config_flow.py`:

```python
"""Tests for adding a beacon plugged into Home Assistant by hand."""

from __future__ import annotations

from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_IGNORE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.blinkybeacon.const import DOMAIN

from .conftest import BASE, HOST, PORT, status_json
from .fake_usb import FLASH, STOP, FakeUsb, tick


async def _start(hass: HomeAssistant) -> dict[str, Any]:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


async def _to_usb(hass: HomeAssistant) -> dict[str, Any]:
    result = await _start(hass)
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "usb"}
    )


async def _to_name(hass: HomeAssistant, port: str = "1-1") -> dict[str, Any]:
    result = await _to_usb(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"usb_port": port}
    )
    await hass.async_block_till_done()
    return result


def _field(result: dict[str, Any], name: str) -> tuple[Any, Any]:
    """The schema key and validator of a form field."""
    return next(
        (key, value)
        for key, value in result["data_schema"].schema.items()
        if key == name
    )


def _ignored(port: str) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, source=SOURCE_IGNORE, unique_id=f"usb:{port}", data={}
    )


async def test_menu_when_a_usb_beacon_waits(
    hass: HomeAssistant, fake_usb: FakeUsb
) -> None:
    """With an unnamed beacon plugged in, the first step asks where it is."""
    fake_usb.plug("1-1")

    result = await _start(hass)

    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["tray", "usb"]


async def test_tray_form_when_no_usb_beacon_waits(hass: HomeAssistant) -> None:
    """With none plugged in, the first step is the tray form."""
    result = await _start(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "tray"


async def test_tray_from_the_menu(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, fake_usb: FakeUsb
) -> None:
    """Choosing the tray from the menu adds a tray as before."""
    fake_usb.plug("1-1")
    aioclient_mock.get(f"{BASE}/status", json=status_json())
    result = await _start(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "tray"}
    )
    assert result["step_id"] == "tray"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": HOST, "port": PORT, "name": "Home beacon"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"host": HOST, "port": PORT}


async def test_usb_lists_unnamed_ports(
    hass: HomeAssistant, fake_usb: FakeUsb, usb_entry: MockConfigEntry
) -> None:
    """Ports with a named beacon are left out; an ignored offer is listed."""
    fake_usb.plug("1-1", "hidraw0")
    fake_usb.plug("1-2", "hidraw1")
    fake_usb.plug("1-3.1", "hidraw2")
    usb_entry.add_to_hass(hass)
    _ignored("1-2").add_to_hass(hass)

    result = await _to_usb(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "usb"
    _, ports = _field(result, "usb_port")
    assert ports.container == {"1-2": "USB port 1-2", "1-3.1": "USB port 1-3.1"}


async def test_naming_flashes_then_adds_the_beacon(
    hass: HomeAssistant, fake_usb: FakeUsb, freezer: FrozenDateTimeFactory
) -> None:
    """The beacon flashes while it is named, stops on submit, and is added."""
    fake_usb.plug("1-1")

    result = await _to_name(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "name"
    assert result["description_placeholders"] == {"port": "1-1"}
    key, _ = _field(result, "name")
    assert key.default() == "Beacon on USB port 1-1"
    assert fake_usb.written() == [STOP, FLASH]

    await tick(hass, freezer, 5)
    assert fake_usb.written() == [STOP, FLASH, FLASH]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "  Team A beacon "}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Team A beacon"
    assert result["data"] == {"usb_port": "1-1"}
    assert result["result"].unique_id == "usb:1-1"
    assert fake_usb.written() == [STOP, FLASH, FLASH, STOP, STOP]
    assert hass.states.get("light.team_a_beacon").state == "off"


async def test_closing_the_naming_step_stops_the_beacon(
    hass: HomeAssistant, fake_usb: FakeUsb, freezer: FrozenDateTimeFactory
) -> None:
    """A naming step closed without an answer stops the beacon for good."""
    fake_usb.plug("1-1")
    result = await _to_name(hass)

    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()
    await tick(hass, freezer, 10)

    assert fake_usb.written() == [STOP, FLASH, STOP]
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_blank_name_is_refused(hass: HomeAssistant, fake_usb: FakeUsb) -> None:
    """A blank name keeps the form open, and the beacon keeps flashing."""
    fake_usb.plug("1-1")
    result = await _to_name(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "   "}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"name": "name_required"}
    assert fake_usb.written() == [STOP, FLASH]
    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()


async def test_no_usb_beacon_left_shows_the_tray_form(
    hass: HomeAssistant, fake_usb: FakeUsb
) -> None:
    """A beacon unplugged before its port is listed leads to the tray form."""
    fake_usb.plug("1-1")
    result = await _start(hass)
    fake_usb.unplug()

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "usb"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "tray"
    assert result["errors"] == {"base": "no_usb_beacon"}


async def test_port_emptied_before_it_is_picked(
    hass: HomeAssistant, fake_usb: FakeUsb
) -> None:
    """A port that empties while the list is shown is refused, and the list redone."""
    fake_usb.plug("1-1", "hidraw0")
    fake_usb.plug("1-2", "hidraw1")
    result = await _to_usb(hass)
    fake_usb.unplug("hidraw0")

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"usb_port": "1-1"}
    )

    assert result["step_id"] == "usb"
    assert result["errors"] == {"base": "usb_beacon_gone"}
    _, ports = _field(result, "usb_port")
    assert ports.container == {"1-2": "USB port 1-2"}


async def test_port_added_meanwhile_aborts(
    hass: HomeAssistant, fake_usb: FakeUsb, usb_entry: MockConfigEntry
) -> None:
    """A port added by another flow while this one names it aborts, and stops."""
    fake_usb.plug("1-1")
    result = await _to_name(hass)
    usb_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Team B beacon"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert fake_usb.written() == [STOP, FLASH, STOP]


async def test_ignored_offer_added_by_hand(
    hass: HomeAssistant, fake_usb: FakeUsb
) -> None:
    """A beacon whose offer was ignored can still be added by hand."""
    fake_usb.plug("1-1")
    _ignored("1-1").add_to_hass(hass)
    result = await _to_name(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Team A beacon"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    entries = hass.config_entries.async_entries(DOMAIN, include_ignore=True)
    assert [(e.source, e.unique_id) for e in entries] == [("user", "usb:1-1")]


async def test_reconfigure_a_usb_beacon_aborts(
    hass: HomeAssistant, usb_entry: MockConfigEntry
) -> None:
    """A USB beacon has no address to change; reconfigure says so."""
    usb_entry.add_to_hass(hass)

    result = await usb_entry.start_reconfigure_flow(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "usb_not_reconfigurable"
    assert usb_entry.data == {"usb_port": "1-1"}
```

- [x] **Step 2: Run them; expect the red state below.**

Run: `(cd "$BB" && timeout 300 .venv/bin/pytest -q -p no:cacheprovider tests/test_usb_config_flow.py)`

Expected (recorded): the first step is still the tray form at `user`, with no menu, port list or naming step:

```text
=========================== short test summary info ============================
FAILED tests/test_usb_config_flow.py::test_menu_when_a_usb_beacon_waits - Ass...
FAILED tests/test_usb_config_flow.py::test_tray_form_when_no_usb_beacon_waits
FAILED tests/test_usb_config_flow.py::test_tray_from_the_menu - homeassistant...
FAILED tests/test_usb_config_flow.py::test_usb_lists_unnamed_ports - Assertio...
FAILED tests/test_usb_config_flow.py::test_naming_flashes_then_adds_the_beacon
FAILED tests/test_usb_config_flow.py::test_closing_the_naming_step_stops_the_beacon
FAILED tests/test_usb_config_flow.py::test_blank_name_is_refused - AssertionE...
FAILED tests/test_usb_config_flow.py::test_no_usb_beacon_left_shows_the_tray_form
FAILED tests/test_usb_config_flow.py::test_port_emptied_before_it_is_picked
FAILED tests/test_usb_config_flow.py::test_port_added_meanwhile_aborts - Asse...
FAILED tests/test_usb_config_flow.py::test_ignored_offer_added_by_hand - Asse...
FAILED tests/test_usb_config_flow.py::test_reconfigure_a_usb_beacon_aborts - ...
12 failed in 0.96s
```

- [x] **Step 3: Replace `custom_components/blinkybeacon/config_flow.py` with:**

```python
"""Add a beacon from the UI: on a PC running the tray, or plugged in here."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .api import (
    BlinkyBeaconClient,
    BlinkyBeaconConnectionError,
    BlinkyBeaconError,
    BlinkyBeaconNotConnectedError,
)
from .const import CONF_USB_PORT, DEFAULT_NAME, DEFAULT_PORT, DOMAIN
from .usb_beacon import UsbBeacon, find_beacons, usb_unique_id

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
    }
)
RECONFIGURE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
    }
)


def normalize_host(raw: str, port: int) -> tuple[str, int]:
    """Reduce what was typed in the host field to a host and a port.

    Accepts a bare host, host:port, [ipv6]:port, a bare IPv6 address, or any of
    these as an http(s) URL with a trailing slash. Raises ValueError otherwise.
    """
    value = raw.strip()
    for scheme in ("http://", "https://"):
        if value.lower().startswith(scheme):
            value = value[len(scheme) :]
    value = value.rstrip("/")
    if not value or "/" in value:
        raise ValueError(raw)

    if value.startswith("["):
        host, sep, rest = value[1:].partition("]")
        if not sep:
            raise ValueError(raw)
        if rest:
            if not rest.startswith(":"):
                raise ValueError(raw)
            port = _port(rest[1:], raw)
    elif value.count(":") == 1:
        host, _, port_text = value.partition(":")
        port = _port(port_text, raw)
    else:
        host = value
    if not host:
        raise ValueError(raw)
    return host, port


def _port(text: str, raw: str) -> int:
    if not text.isdigit() or not 1 <= int(text) <= 65535:
        raise ValueError(raw)
    return int(text)


class BlinkyBeaconConfigFlow(ConfigFlow, domain=DOMAIN):
    """One flow per beacon: a tray on a PC, or a beacon in a USB port here."""

    VERSION = 1

    def __init__(self) -> None:
        self._usb_port = ""
        self._flasher: UsbBeacon | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask where the beacon is plugged in, if a USB beacon is waiting."""
        if await self._async_unnamed_ports():
            return self.async_show_menu(step_id="user", menu_options=["tray", "usb"])
        return await self.async_step_tray()

    async def async_step_tray(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the tray's address and a name for the beacon."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                host, port = normalize_host(
                    user_input[CONF_HOST], user_input[CONF_PORT]
                )
            except ValueError:
                errors[CONF_HOST] = "invalid_host"
            else:
                await self.async_set_unique_id(f"{host}:{port}".lower())
                self._abort_if_unique_id_configured()
                if not (error := await self._async_check(host, port)):
                    return self.async_create_entry(
                        title=user_input[CONF_NAME],
                        data={CONF_HOST: host, CONF_PORT: port},
                    )
                errors["base"] = error

        return self.async_show_form(
            step_id="tray",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_usb(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """List the USB ports holding a beacon with no name yet."""
        ports = await self._async_unnamed_ports()
        if not ports:
            return self.async_show_form(
                step_id="tray",
                data_schema=USER_SCHEMA,
                errors={"base": "no_usb_beacon"},
            )
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_USB_PORT] in ports:
                self._usb_port = user_input[CONF_USB_PORT]
                await self.async_set_unique_id(
                    usb_unique_id(self._usb_port), raise_on_progress=False
                )
                self._abort_if_unique_id_configured()
                return await self.async_step_name()
            errors["base"] = "usb_beacon_gone"
        return self.async_show_form(
            step_id="usb",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USB_PORT): vol.In(
                        {port: f"USB port {port}" for port in ports}
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_name(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Flash the beacon while the user names it."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if name := user_input[CONF_NAME].strip():
                await self._async_stop_flashing()
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=name, data={CONF_USB_PORT: self._usb_port}
                )
            errors[CONF_NAME] = "name_required"
        elif self._flasher is None:
            self._flasher = UsbBeacon(self.hass, self._usb_port)
            await self._flasher.async_start()
            with suppress(BlinkyBeaconNotConnectedError):
                await self._flasher.flash()
        return self.async_show_form(
            step_id="name",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME, default=f"Beacon on USB port {self._usb_port}"
                    ): str
                }
            ),
            description_placeholders={"port": self._usb_port},
            errors=errors,
        )

    @callback
    def async_remove(self) -> None:
        """Stop the beacon if the naming step was left without an answer."""
        if (flasher := self._flasher) is not None:
            self._flasher = None
            self.hass.async_create_task(flasher.async_close())

    async def _async_stop_flashing(self) -> None:
        if (flasher := self._flasher) is not None:
            self._flasher = None
            await flasher.async_close()

    async def _async_unnamed_ports(self) -> list[str]:
        """Ports holding a beacon no entry names; an ignored offer names none."""
        ports = await self.hass.async_add_executor_job(find_beacons)
        named = self._async_current_ids(include_ignore=False)
        return sorted(port for port in ports if usb_unique_id(port) not in named)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Point an existing beacon at its tray's new address."""
        entry = self._get_reconfigure_entry()
        if CONF_USB_PORT in entry.data:
            return self.async_abort(reason="usb_not_reconfigurable")
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                host, port = normalize_host(
                    user_input[CONF_HOST], user_input[CONF_PORT]
                )
            except ValueError:
                errors[CONF_HOST] = "invalid_host"
            else:
                unique_id = f"{host}:{port}".lower()
                await self.async_set_unique_id(unique_id)
                if unique_id != entry.unique_id:
                    self._abort_if_unique_id_configured()
                if not (error := await self._async_check(host, port)):
                    return self.async_update_reload_and_abort(
                        entry,
                        unique_id=unique_id,
                        data_updates={CONF_HOST: host, CONF_PORT: port},
                    )
                errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                RECONFIGURE_SCHEMA, user_input or entry.data
            ),
            errors=errors,
        )

    async def _async_check(self, host: str, port: int) -> str | None:
        """Read /status once; return an error key, or None if the tray answered."""
        client = BlinkyBeaconClient(async_get_clientsession(self.hass), host, port)
        try:
            await client.status()
        except BlinkyBeaconConnectionError:
            return "cannot_connect"
        except BlinkyBeaconError:
            return "invalid_reply"
        return None
```

- [x] **Step 4: Add the flow's text** to `custom_components/blinkybeacon/strings.json`, three replacements.

(a) Replace

```json
      "user": {
        "title": "Add a BlinkyBeacon",
        "description": "Enter the address of the PC running blinkybeacon-tray. In the tray's settings, the bind address must be 0.0.0.0 or this PC's LAN address, not 127.0.0.1.",
        "data": {
```

with

```json
      "user": {
        "title": "Add a BlinkyBeacon",
        "description": "Where is the beacon plugged in?",
        "menu_options": {
          "tray": "Into a PC running blinkybeacon-tray",
          "usb": "Into this Home Assistant"
        }
      },
      "tray": {
        "title": "Add a beacon plugged into a PC",
        "description": "Enter the address of the PC running blinkybeacon-tray. In the tray's settings, the bind address must be 0.0.0.0 or this PC's LAN address, not 127.0.0.1.\n\nA beacon plugged into this Home Assistant is offered as a choice here once it is plugged in.",
        "data": {
```

(b) Replace

```json
          "name": "What to call this beacon, for example Home beacon."
        }
      },
      "reconfigure": {
```

with

```json
          "name": "What to call this beacon, for example Home beacon."
        }
      },
      "usb": {
        "title": "Add a beacon plugged into this Home Assistant",
        "description": "Pick the USB port the beacon is plugged into. Only ports holding a beacon that has no name yet are listed.",
        "data": {
          "usb_port": "USB port"
        }
      },
      "name": {
        "title": "Name the beacon",
        "description": "The beacon on USB port {port} is flashing, so you can tell which one it is. It stops when you submit or close this form.",
        "data": {
          "name": "Name"
        },
        "data_description": {
          "name": "What this beacon means, for example Team A."
        }
      },
      "reconfigure": {
```

(c) Replace

```json
      "invalid_host": "Enter a host name or IP address, optionally with :port, without a path."
    },
    "abort": {
      "already_configured": "This tray is already added.",
      "reconfigure_successful": "The beacon now uses the new address."
```

with

```json
      "invalid_host": "Enter a host name or IP address, optionally with :port, without a path.",
      "no_usb_beacon": "No beacon without a name is plugged into this Home Assistant. To add a beacon plugged into a PC, fill in this form.",
      "usb_beacon_gone": "That beacon is no longer plugged in. Pick another port.",
      "name_required": "Enter a name for the beacon."
    },
    "abort": {
      "already_configured": "This beacon is already added.",
      "reconfigure_successful": "The beacon now uses the new address.",
      "usb_not_reconfigurable": "A beacon plugged into this Home Assistant is known by its USB port, so there is nothing to change here. To use another port, plug it in there, add it, and remove this one."
```

then copy it to `translations/en.json` and check `cmp` is silent.

- [x] **Step 5: Run the whole suite, lint and format; expect green** (the 0.1.0 flow tests included, unmodified).

Run: `(cd "$BB" && timeout 300 .venv/bin/pytest -q -p no:cacheprovider && .venv/bin/ruff check custom_components tests && .venv/bin/ruff format --check custom_components tests && cmp custom_components/blinkybeacon/strings.json custom_components/blinkybeacon/translations/en.json)`

Expected: `126 passed in 6.33s`, `All checks passed!`, all files already formatted, `cmp` silent.

- [x] **Step 6: Commit and push.**

```bash
P=blinkybeacon-hassio/custom_components/blinkybeacon
F="$P/config_flow.py $P/strings.json $P/translations/en.json blinkybeacon-hassio/tests/test_usb_config_flow.py"
(cd "$W" && command grep -c -i -F -f "$NAMES_LIST" $F)   # 0 for each file
git -C "$W" add $F
git -C "$W" commit -m "blinkybeacon-hassio: add a beacon plugged into Home Assistant by hand: pick its USB port, name it while it flashes" -- $F
git -C "$W" branch --show-current   # wt/blinkybeacon-usb
git -C "$W" log --format=%B main..wt/blinkybeacon-usb | command grep -c -i -F -f "$NAMES_LIST"   # 0
git -C "$W" log -p main..wt/blinkybeacon-usb | command grep -c -F -f "$SECRETS_LIST"   # 0
git -C "$W" push origin wt/blinkybeacon-usb
```

### Task 6: Offer each beacon as soon as it is plugged in

**Files:**
- Create: `custom_components/blinkybeacon/usb_scan.py`, `tests/test_usb_discovery.py`
- Modify: `custom_components/blinkybeacon/const.py`, `custom_components/blinkybeacon/__init__.py`, `custom_components/blinkybeacon/config_flow.py`, `custom_components/blinkybeacon/strings.json`, `custom_components/blinkybeacon/translations/en.json`

**Interfaces:**
- Consumes: `find_beacons`, `usb_unique_id` (Task 1); the flow's `async_step_name` and `self._usb_port` (Task 5).
- Produces (`const.py`): `USB_SCAN_INTERVAL = timedelta(seconds=10)`.
- Produces (`usb_scan.py`): `DATA_USB_SCAN: HassKey[UsbScan]`, `async_start_usb_scan(hass, entry) -> None` (callback; counts the entry, removes it on unload), `class UsbScan` with `async_add(entry_id)`, `async_remove(entry_id)`; every `USB_SCAN_INTERVAL` while at least one entry is counted, each port from `find_beacons` with no entry (ignored ones included) and no flow in progress for `usb:<port>` gets `discovery_flow.async_create_flow(hass, DOMAIN, context={"source": SOURCE_INTEGRATION_DISCOVERY}, data={"usb_port": port})`.
- Produces (`config_flow.py`): `async_step_integration_discovery(discovery_info)` (unique id, abort if configured, `title_placeholders={"port": port}`) and `async_step_discovery_confirm` (confirm only, lights nothing; port empty when opened → abort `usb_beacon_gone` with `{"port"}`; submitted → `name`).

- [x] **Step 1: Write the failing tests.** Create `tests/test_usb_discovery.py`:

```python
"""Tests for offering a beacon as soon as it is plugged into Home Assistant."""

from __future__ import annotations

from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import (
    SOURCE_IGNORE,
    SOURCE_INTEGRATION_DISCOVERY,
    SOURCE_USER,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.blinkybeacon.const import DOMAIN

from .conftest import BASE, setup_integration, status_json
from .fake_usb import FLASH, STOP, FakeUsb, tick


@pytest.fixture
async def tray(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> MockConfigEntry:
    """A loaded tray entry, so the scan runs; set up on the frozen clock."""
    aioclient_mock.get(f"{BASE}/status", json=status_json())
    await setup_integration(hass, mock_config_entry)
    return mock_config_entry


def _offers(hass: HomeAssistant) -> list[dict[str, Any]]:
    return [
        flow
        for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        if flow["context"]["source"] == SOURCE_INTEGRATION_DISCOVERY
    ]


async def test_offered_within_ten_seconds(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    tray: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A beacon plugged in is offered by its port, and nothing lights up yet."""
    fake_usb.plug("1-2")

    await tick(hass, freezer, 9)
    assert _offers(hass) == []

    await tick(hass, freezer, 1)
    [offer] = _offers(hass)
    assert offer["step_id"] == "discovery_confirm"
    assert offer["context"]["unique_id"] == "usb:1-2"
    assert offer["context"]["title_placeholders"] == {"port": "1-2"}
    assert fake_usb.written() == []


async def test_not_offered_without_a_loaded_entry(
    hass: HomeAssistant, fake_usb: FakeUsb, freezer: FrozenDateTimeFactory
) -> None:
    """With no beacon set up, nothing scans; the beacon is added by hand."""
    fake_usb.plug("1-1")

    await tick(hass, freezer, 30)

    assert _offers(hass) == []


async def test_offered_once(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    tray: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A port with an offer waiting is not offered again."""
    fake_usb.plug("1-2")

    for _ in range(3):
        await tick(hass, freezer, 10)

    assert len(_offers(hass)) == 1


async def test_named_and_ignored_ports_not_offered(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    usb_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A port that has an entry, or whose offer was ignored, is not offered."""
    fake_usb.plug("1-1", "hidraw0")
    fake_usb.plug("1-2", "hidraw1")
    MockConfigEntry(
        domain=DOMAIN, source=SOURCE_IGNORE, unique_id="usb:1-2", data={}
    ).add_to_hass(hass)
    await setup_integration(hass, usb_entry)

    await tick(hass, freezer, 10)

    assert _offers(hass) == []


async def test_scan_ends_with_the_last_loaded_entry(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    tray: MockConfigEntry,
    usb_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The scan runs while any entry is loaded, and stops after the last one."""
    fake_usb.plug("1-1", "hidraw0")
    await setup_integration(hass, usb_entry)
    assert await hass.config_entries.async_unload(usb_entry.entry_id)
    fake_usb.plug("1-2", "hidraw1")

    await tick(hass, freezer, 10)
    [offer] = _offers(hass)
    hass.config_entries.flow.async_abort(offer["flow_id"])

    assert await hass.config_entries.async_unload(tray.entry_id)
    await tick(hass, freezer, 10)
    assert _offers(hass) == []


async def test_offer_flashes_on_the_naming_step_and_adds(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    tray: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Opening the offer goes to the naming step, which flashes the beacon."""
    fake_usb.plug("1-1")
    await tick(hass, freezer, 10)
    [offer] = _offers(hass)

    result = await hass.config_entries.flow.async_configure(offer["flow_id"], {})
    await hass.async_block_till_done()

    assert result["step_id"] == "name"
    assert fake_usb.written() == [STOP, FLASH]

    result = await hass.config_entries.flow.async_configure(
        offer["flow_id"], {"name": "Team A beacon"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "usb:1-1"
    assert result["result"].source == SOURCE_INTEGRATION_DISCOVERY


async def test_offer_opened_after_unplug_aborts(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    tray: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """An offer opened after its beacon was unplugged says so and closes."""
    fake_usb.plug("1-1")
    await tick(hass, freezer, 10)
    [offer] = _offers(hass)
    fake_usb.unplug()

    # Opening a waiting flow in the UI runs its step again with no input.
    result = await hass.config_entries.flow.async_configure(offer["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "usb_beacon_gone"
    assert result["description_placeholders"] == {"port": "1-1"}


async def test_adding_by_hand_closes_the_offer(
    hass: HomeAssistant,
    fake_usb: FakeUsb,
    tray: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A beacon added by hand while it is offered leaves no offer behind."""
    fake_usb.plug("1-1")
    await tick(hass, freezer, 10)
    assert len(_offers(hass)) == 1

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "usb"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"usb_port": "1-1"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Team A beacon"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _offers(hass) == []


async def test_offer_for_a_named_port_aborts(
    hass: HomeAssistant, usb_entry: MockConfigEntry
) -> None:
    """A second set-up for a port that has an entry is aborted."""
    usb_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_INTEGRATION_DISCOVERY},
        data={"usb_port": "1-1"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
```

- [x] **Step 2: Run them; expect the red state below.**

Run: `(cd "$BB" && timeout 300 .venv/bin/pytest -q -p no:cacheprovider tests/test_usb_discovery.py)`

Expected (recorded): nothing scans, and a discovery flow has no step of its own to stop at. Three tests already pass here, since they check that nothing is offered or that a configured port aborts, which Home Assistant's default discovery step also does: `test_not_offered_without_a_loaded_entry`, `test_named_and_ignored_ports_not_offered`, `test_offer_for_a_named_port_aborts`:

```text
=========================== short test summary info ============================
FAILED tests/test_usb_discovery.py::test_offered_within_ten_seconds - ValueEr...
FAILED tests/test_usb_discovery.py::test_offered_once - assert 0 == 1
FAILED tests/test_usb_discovery.py::test_scan_ends_with_the_last_loaded_entry
FAILED tests/test_usb_discovery.py::test_offer_flashes_on_the_naming_step_and_adds
FAILED tests/test_usb_discovery.py::test_offer_opened_after_unplug_aborts - V...
FAILED tests/test_usb_discovery.py::test_adding_by_hand_closes_the_offer - as...
6 failed, 3 passed in 0.93s
```

- [x] **Step 3: Add the scan interval.** In `custom_components/blinkybeacon/const.py`, after `KEEPALIVE_INTERVAL = timedelta(seconds=5)`, add `USB_SCAN_INTERVAL = timedelta(seconds=10)`.

- [x] **Step 4: Create `custom_components/blinkybeacon/usb_scan.py`:**

```python
"""Offers each beacon plugged into a USB port that no entry names yet."""

from __future__ import annotations

from datetime import datetime
from functools import partial

from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY, ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import discovery_flow
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util.hass_dict import HassKey

from .const import CONF_USB_PORT, DOMAIN, USB_SCAN_INTERVAL
from .usb_beacon import find_beacons, usb_unique_id

DATA_USB_SCAN: HassKey[UsbScan] = HassKey(f"{DOMAIN}_usb_scan")


@callback
def async_start_usb_scan(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Scan while at least one entry is loaded; unloading this one ends its part."""
    if (scan := hass.data.get(DATA_USB_SCAN)) is None:
        scan = hass.data[DATA_USB_SCAN] = UsbScan(hass)
    scan.async_add(entry.entry_id)
    entry.async_on_unload(partial(scan.async_remove, entry.entry_id))


class UsbScan:
    """Looks for unnamed beacons every few seconds while any entry is loaded."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._entry_ids: set[str] = set()
        self._cancel: CALLBACK_TYPE | None = None

    @callback
    def async_add(self, entry_id: str) -> None:
        """Count a loaded entry; the first one starts the scan."""
        self._entry_ids.add(entry_id)
        if self._cancel is None:
            self._cancel = async_track_time_interval(
                self._hass,
                self._async_scan,
                USB_SCAN_INTERVAL,
                name="BlinkyBeacon USB scan",
                cancel_on_shutdown=True,
            )

    @callback
    def async_remove(self, entry_id: str) -> None:
        """Forget an unloaded entry; the last one stops the scan."""
        self._entry_ids.discard(entry_id)
        if not self._entry_ids and self._cancel is not None:
            self._cancel()
            self._cancel = None

    async def _async_scan(self, _now: datetime) -> None:
        ports = await self._hass.async_add_executor_job(find_beacons)
        for port in ports:
            unique_id = usb_unique_id(port)
            if self._hass.config_entries.async_entry_for_domain_unique_id(
                DOMAIN, unique_id
            ) or self._hass.config_entries.flow.async_progress_by_handler(
                DOMAIN,
                include_uninitialized=True,
                match_context={"unique_id": unique_id},
            ):
                continue
            discovery_flow.async_create_flow(
                self._hass,
                DOMAIN,
                context={"source": SOURCE_INTEGRATION_DISCOVERY},
                data={CONF_USB_PORT: port},
            )
```

- [x] **Step 5: Replace `custom_components/blinkybeacon/__init__.py` with:**

```python
"""The BlinkyBeacon integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import BlinkyBeaconClient
from .const import CONF_USB_PORT, DOMAIN
from .coordinator import BlinkyBeaconConfigEntry, BlinkyBeaconCoordinator
from .repairs import async_track_missing
from .services import async_setup_services
from .usb_beacon import UsbBeacon
from .usb_scan import async_start_usb_scan

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.LIGHT]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions once, for every beacon."""
    async_setup_services(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: BlinkyBeaconConfigEntry
) -> bool:
    """Set up a beacon; retried later if its tray does not answer."""
    client: BlinkyBeaconClient | UsbBeacon
    if (usb_port := entry.data.get(CONF_USB_PORT)) is not None:
        client = UsbBeacon(hass, usb_port)
        await client.async_start()
        entry.async_on_unload(client.async_close)
    else:
        client = BlinkyBeaconClient(
            async_get_clientsession(hass), entry.data[CONF_HOST], entry.data[CONF_PORT]
        )
    coordinator = BlinkyBeaconCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    async def _async_on_stop(_event: Event) -> None:
        # HA does not unload entries when it shuts down.
        await coordinator.async_shutdown_stop()

    entry.async_on_unload(
        hass.bus.async_listen(EVENT_HOMEASSISTANT_STOP, _async_on_stop)
    )
    if usb_port is not None:
        async_track_missing(hass, coordinator)
    async_start_usb_scan(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: BlinkyBeaconConfigEntry
) -> bool:
    """Unload a beacon, first sending any pending timed stop."""
    await entry.runtime_data.async_shutdown_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
```

- [x] **Step 6: Add the offer steps to `custom_components/blinkybeacon/config_flow.py`.** Add the import line `from homeassistant.helpers.typing import DiscoveryInfoType` after `from homeassistant.helpers.aiohttp_client import async_get_clientsession`, and insert these two methods immediately above `async def async_step_name(`:

```python
    async def async_step_integration_discovery(
        self, discovery_info: DiscoveryInfoType
    ) -> ConfigFlowResult:
        """A beacon found in a USB port that no entry names."""
        self._usb_port = discovery_info[CONF_USB_PORT]
        await self.async_set_unique_id(usb_unique_id(self._usb_port))
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"port": self._usb_port}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer the beacon; nothing lights up until the user opens the offer."""
        if user_input is not None:
            return await self.async_step_name()
        if self._usb_port not in await self.hass.async_add_executor_job(find_beacons):
            return self.async_abort(
                reason="usb_beacon_gone",
                description_placeholders={"port": self._usb_port},
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={"port": self._usb_port},
        )
```

- [x] **Step 7: Add the offer's text** to `custom_components/blinkybeacon/strings.json`, three replacements.

(a) Replace

```json
  "config": {
    "step": {
```

with

```json
  "config": {
    "flow_title": "BlinkyBeacon found on USB port {port}",
    "step": {
```

(b) Replace

```json
      "name": {
        "title": "Name the beacon",
```

with

```json
      "discovery_confirm": {
        "title": "BlinkyBeacon found",
        "description": "A beacon is plugged into USB port {port} of this Home Assistant. Add it? It flashes on the next step so you can tell which one it is."
      },
      "name": {
        "title": "Name the beacon",
```

(c) Replace

```json
      "already_configured": "This beacon is already added.",
```

with

```json
      "already_configured": "This beacon is already added.",
      "usb_beacon_gone": "The beacon is no longer plugged into USB port {port}.",
```

then copy it to `translations/en.json` and check `cmp` is silent.

- [x] **Step 8: Run the whole suite, lint and format; expect green.**

Run: `(cd "$BB" && timeout 300 .venv/bin/pytest -q -p no:cacheprovider && .venv/bin/ruff check custom_components tests && .venv/bin/ruff format --check custom_components tests && cmp custom_components/blinkybeacon/strings.json custom_components/blinkybeacon/translations/en.json)`

Expected: `135 passed in 8.46s`, `All checks passed!`, all files already formatted, `cmp` silent.

- [x] **Step 9: Commit and push.**

```bash
P=blinkybeacon-hassio/custom_components/blinkybeacon
F="$P/usb_scan.py $P/const.py $P/__init__.py $P/config_flow.py $P/strings.json $P/translations/en.json blinkybeacon-hassio/tests/test_usb_discovery.py"
(cd "$W" && command grep -c -i -F -f "$NAMES_LIST" $F)   # 0 for each file
git -C "$W" add $F
git -C "$W" commit -m "blinkybeacon-hassio: offer each unnamed beacon plugged into Home Assistant within 10 seconds while a beacon is set up; nothing lights until the offer is opened" -- $F
git -C "$W" branch --show-current   # wt/blinkybeacon-usb
git -C "$W" log --format=%B main..wt/blinkybeacon-usb | command grep -c -i -F -f "$NAMES_LIST"   # 0
git -C "$W" log -p main..wt/blinkybeacon-usb | command grep -c -F -f "$SECRETS_LIST"   # 0
git -C "$W" push origin wt/blinkybeacon-usb
```

### Task 7: README, the branch gates, and the real-hardware smoke

**Files:**
- Modify: `README.md`

**Interfaces:** none; documentation and gates. The hardware smoke at the end is the **master's, with the owner**, after the worker's DONE; the worker writes it into the retro as steps to run, and runs none of it.

- [x] **Step 1: Update `README.md`** with these replacements, each "replace" text exactly as on `main`.

(1) Replace

```markdown
the USB beacon light driven by `blinkybeacon-tray`. Each tray becomes a device in Home
Assistant, so automations and scripts can spin, flash and stop it — for example, a Zigbee
button press that lights the beacon of the team that pressed it.
```

with

```markdown
the USB beacon light. A beacon plugged into a PC is driven through `blinkybeacon-tray` on that
PC; a beacon plugged straight into the Home Assistant machine is driven by the integration
itself, with no tray. Each beacon becomes a device in Home Assistant, so automations and
scripts can spin, flash and stop it — for example, a Zigbee button press that lights the
beacon of the team that pressed it.
```

(2) Replace

```markdown
For each beacon (one tray, one `host:port`):
```

with

```markdown
For each beacon (a tray at one `host:port`, or one USB port of the Home Assistant machine):
```

(3) Replace

```markdown
| **USB connected** (diagnostic) | Whether the tray sees its USB light. |
```

with

```markdown
| **USB connected** (diagnostic) | Whether the tray sees its USB light, or whether the beacon is in its USB port. |
```

(4) Replace

```markdown
error naming the beacon**, and the automation's trace shows it. When several beacons are
```

with

```markdown
error naming the beacon** (and, for a beacon plugged into Home Assistant, its USB port), and
the automation's trace shows it. When several beacons are
```

(5) Replace

```markdown
Settings → Devices & services → **Add integration** → **BlinkyBeacon**, then enter:
```

with

```markdown
Settings → Devices & services → **Add integration** → **BlinkyBeacon**. When a beacon with no
name is plugged into the Home Assistant machine, the first step asks where the beacon is
plugged in: choose **Into a PC running blinkybeacon-tray** for a tray, or see
[Beacons plugged into Home Assistant](#beacons-plugged-into-home-assistant). Otherwise the
tray form opens straight away. For a tray, enter:
```

(6) Replace

```markdown
address changes, use **Reconfigure** on the beacon's entry.
```

with

```markdown
address changes, use **Reconfigure** on the beacon's entry.

## Beacons plugged into Home Assistant

A beacon can also be plugged straight into a USB port of the machine running Home Assistant.
The integration drives it itself; no tray is needed. Several beacons can be plugged in at
once, each with its own name, for example one per team. This was tested on Home Assistant
OS; another installation needs Home Assistant's own process to be able to write the
machine's `/dev/hidraw*` devices.

**Each beacon is known by the USB port it is plugged into**, because the beacons are
identical and carry no serial number. Keep each beacon in its port: label the ports or the
hub, and plug the beacons in the same way every time. A beacon plugged into a different port
is a new beacon to be named.

**Adding one.** While at least one BlinkyBeacon is set up, a beacon plugged into a USB port
that has no name yet is offered within about 10 seconds under Settings → Devices & services,
as *BlinkyBeacon found on USB port 1-1*. Select **Add**, then name it. You can also add one
by hand at any time: **Add integration** → **BlinkyBeacon** → **Into this Home Assistant**,
then pick its port from the list of ports holding a beacon with no name. While you name it,
the beacon flashes, so you can tell which one it is; it stops when you submit or close the
form. The port, such as `1-1` or `1-3.2` behind a hub, is how Linux numbers the machine's
USB ports.

**When a beacon is unplugged**, its light is unavailable and its **USB connected** sensor is
off, as for a tray whose light is unplugged, and an action aimed at it fails with an error
naming it and its port. A notice in Settings → System → **Repairs** says *Team A is missing from USB
port 1-1* (with your beacon's name). Plug it back into the same port and the notice clears by
itself within about 10 seconds, the beacon idle; its name, entities and automations are kept.
If the beacon is not coming back, open the notice and submit to remove it.

Disabling, reloading or removing a beacon's entry stops the beacon.

## Troubleshooting

**A beacon on a tray stops by itself 1–2 seconds after it starts.** The tray's `dashboard`
build has a watcher that, while a dashboard URL and token are set in the tray's settings,
sets the beacon back to idle on each of its polls (every 2 seconds by default) when its
dashboard line has nothing live. Open `http://<pc-address>:1337/settings`: if the dashboard
URL and token are filled in, the watcher drives the light. Clear the URL or the token there,
or run the tray's `main` build, which has no watcher, to drive the beacon from Home
Assistant.
```

(7) Replace

```markdown
  yet.
```

with

```markdown
  yet; several beacons on one machine are supported when they are plugged into Home
  Assistant.
- A beacon plugged into Home Assistant is known only by its USB port; moving it to another
  port makes it a new beacon.
```

- [x] **Step 2: Check the README's claims against the code** (each one is pinned by a test above): offered "within about 10 seconds" (`USB_SCAN_INTERVAL`, `test_offered_within_ten_seconds`); the notice clears "within about 10 seconds" of a replug (keepalive 5 s, then the 5 s poll: `test_raised_when_the_port_empties_and_cleared_on_return`); the flash stops on submit or close (`test_naming_flashes_then_adds_the_beacon`, `test_closing_the_naming_step_stops_the_beacon`); "Disabling, reloading or removing a beacon's entry stops the beacon" (`test_setup_and_unload`). The troubleshooting note restates the tray `dashboard` watcher found on 2026-10-25 (spec §5 carries it). Leak-check the file: `command grep -c -i -F -f "$NAMES_LIST" "$BB/README.md"` → `0`.

- [x] **Step 3: Commit and push the README.**

```bash
F="blinkybeacon-hassio/README.md"
(cd "$W" && command grep -c -i -F -f "$NAMES_LIST" $F)   # 0
git -C "$W" add $F
git -C "$W" commit -m "blinkybeacon-hassio: the README covers beacons plugged into Home Assistant, by their USB port, and why a tray beacon can stop by itself after 1 to 2 seconds" -- $F
git -C "$W" branch --show-current   # wt/blinkybeacon-usb
git -C "$W" log --format=%B main..wt/blinkybeacon-usb | command grep -c -i -F -f "$NAMES_LIST"   # 0
git -C "$W" log -p main..wt/blinkybeacon-usb | command grep -c -F -f "$SECRETS_LIST"   # 0
git -C "$W" push origin wt/blinkybeacon-usb
```

- [x] **Step 4: The branch gates on the head**, each output quoted in the retro with the SHA it ran on:

```bash
BB=$W/blinkybeacon-hassio
git -C "$W" rev-parse --short HEAD
(cd "$BB" && timeout 300 .venv/bin/pytest -q -p no:cacheprovider)          # expect 135 passed in 8.46s (count and time)
(cd "$BB" && .venv/bin/ruff check custom_components tests)                  # All checks passed!
(cd "$BB" && .venv/bin/ruff format --check custom_components tests)         # already formatted
git -C "$W" diff --stat main -- blinkybeacon-hassio/tests/test_api.py blinkybeacon-hassio/tests/test_binary_sensor.py blinkybeacon-hassio/tests/test_config_flow.py blinkybeacon-hassio/tests/test_init.py blinkybeacon-hassio/tests/test_light.py blinkybeacon-hassio/tests/test_services.py   # empty
git -C "$W" diff main -- blinkybeacon-hassio/tests/conftest.py | command grep -c '^-[^-]'   # 0
git -C "$W" diff --stat main -- blinkybeacon-hassio/custom_components/blinkybeacon/manifest.json blinkybeacon-hassio/pyproject.toml   # empty
git -C "$W" diff --name-only main | command grep -v '^blinkybeacon-hassio/'   # empty
```

- [x] **Step 5: The suite once in a copy with no `.git`** (negative environment):

```bash
BB=$W/blinkybeacon-hassio
N=$(mktemp -d)/blinkybeacon-hassio
rsync -a --exclude .venv --exclude .git --exclude __pycache__ "$BB/" "$N/"
ln -s "$BB/.venv" "$N/.venv"
(cd "$N" && test ! -e .git && ! git rev-parse --git-dir >/dev/null 2>&1 && timeout 300 .venv/bin/pytest -q -p no:cacheprovider)   # same count as Step 4, green
```

Record the count and time. No test shells out to git, so the expected outcome is green, not a skip.

- [x] **Step 6: The leak and secret checks over everything written**, quoted in the retro:

```bash
for f in $(git -C "$W" diff --name-only main); do printf '%s ' "$f"; command grep -c -i -F -f "$NAMES_LIST" "$W/$f"; done   # 0 for each
git -C "$W" log --format=%B main..wt/blinkybeacon-usb | command grep -c -i -F -f "$NAMES_LIST"   # 0
git -C "$W" log -p main..wt/blinkybeacon-usb | command grep -c -F -f "$SECRETS_LIST"   # 0
```

- [x] **Step 7: Write the hardware smoke into the retro for the master** (not run by the worker). On the owner's test machine (Home Assistant OS, core 2026.10.4), the master installs the branch's `custom_components/blinkybeacon` and restarts Home Assistant; the owner does the steps marked **(owner)** by hand and says what the beacon did; the master records each result in this plan's Amendments or the ship notes.

  - **M1 — Install.** The branch's integration is loaded (Settings → Devices & services shows BlinkyBeacon; the log has no error from `custom_components.blinkybeacon`).
  - **M2 — Read-only port check.** In the Home Assistant container, with one beacon plugged into a fixed port **(owner)**: the port the integration will use, from `ls -l /sys/class/hidraw/*/device` and the `HID_ID` line of each `device/uevent`. Expected: one `0003:0000340D:00001710` device whose path holds a port such as `1-1`.
  - **M3 — Add by hand.** Add integration → BlinkyBeacon: the menu shows **(owner sees)**; *Into this Home Assistant* lists the port; picking it flashes the beacon **(owner sees)**; submitting a name stops the flash **(owner sees)** and creates the device with its light and "USB connected" sensor on.
  - **M4 — Drive it.** From Developer tools → Actions on the new device: `blinkybeacon.spin`, `blinkybeacon.flash`, `blinkybeacon.stop` **(owner sees each)**, then `blinkybeacon.spin` with `duration: 10`: spins and stops about 10 s later **(owner times it)**; the light's state follows each.
  - **M5 — Unplug and replug (owner).** Unplug the beacon: within about 5 s the light is unavailable, the sensor off, Settings → System → Repairs shows "<name> is missing from USB port <port>"; `blinkybeacon.spin` on it fails in the trace naming the beacon and its port. Plug it back into the same port: within about 10 s the notice is gone and the light available, off; `spin` works.
  - **M6 — The offer.** With the first beacon still set up (so the scan runs), plug it into **another** port **(owner)**: the old device goes missing with its notice, and within about 10 s Settings → Devices & services shows "BlinkyBeacon found on USB port <new port>"; opening it lights nothing **(owner sees)**; submitting goes to the naming step, which flashes **(owner sees)**; naming it adds a second device on the new port.
  - **M7 — The fix.** Open the old device's notice in Repairs and submit: the old entry, device and entities are removed and the notice is gone.
  - **M8 — Unload.** Disable the new entry while the beacon spins: it stops **(owner sees)**; enable it again: the device returns, idle.
  - **M9 — Log check.** The Home Assistant log since M1 holds no error from `custom_components.blinkybeacon`; any warning from `usb_beacon` names an error type and a port only.

- [x] **Step 8: Write the retro and stop** (Status, per-task evidence, the gates with their SHAs, the cost block); the ship (version `0.2.0`, merge, publish) is the master's.
