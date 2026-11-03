# blinkybeacon-hassio — design

**Date:** 2026-10-25 · **Repo:** `clovisd/blinkybeacon-hassio` · **Status:** approved by the owner
("Go, and ship it", 2026-10-25)

## 1. Intent

The owner runs CS matches with two Zigbee buttons (SLZB-01P on an SMLIGHT MR5U coordinator, in
Home Assistant), one per team, home and away. The end goal: a short press calls a tech timeout for
that team, a long press a tac timeout, through the CS server's API.

Before that, the buttons are being tested for range and reliability. The visible signal for the
test is a BlinkyBeacon: the USB beacon light driven by `blinkybeacon-tray`
([clovisd/blinkybeacon-web](https://github.com/clovisd/blinkybeacon-web)), which serves a small
HTTP API.

This repository is a **Home Assistant custom integration for BlinkyBeacon**, so that the beacon is
driven from Home Assistant's own automation and script system. The owner writes the automations
(button press → beacon) in Home Assistant; this integration only knows beacons. A separate
integration for the game server API comes later and is used the same way, side by side in the
same automations.

## 2. Goals, non-goals, anti-goals

**Goals**
- Each tray (one beacon, one `host:port`) is added from the HA UI as its own device. Several
  beacons means several devices.
- Automations can spin, flash and stop a chosen beacon, optionally for a set number of seconds.
- HA shows each beacon's state (idle / spin / flash) and whether its USB light is plugged in.
- A command that does not reach the light **fails visibly** in the automation trace. In a range
  test a silent miss is the worst outcome.
- Installable through HACS as a custom repository.

**Non-goals (this version)**
- Buttons, teams, timeouts or the game server — automations and a later integration do that.
- Several beacons behind one tray (blinkybeacon-web S16, `?beacon=`) — not built tray-side yet.
- The control-route token (blinkybeacon-web S17/S18) — not built tray-side yet.
- Auto-discovery — the tray does not advertise itself.
- Changes to the owner's Home Assistant instance (owner, 2026-10-25: "Nothing to do in HASSIO
  right now, just configure and create the extension").

**Anti-goals**
- An action that reports success while the beacon did nothing.
- Anything that needs the tray changed. The integration works with the tray API as it ships today
  on both lines (`main` v0.4.x and `dashboard`).

## 3. The tray API it uses

From blinkybeacon-web's README and `cmd/blinkybeacon-tray/server.go` (both lines):

| Call | Reply |
|---|---|
| `GET /status` | `200 {"state": "spin"\|"flash"\|"idle", "connected": bool}` |
| `POST /spin`, `/flash`, `/stop` | `200 {"state", "connected": true}` · `503 {"error": "beacon not connected"\|"beacon disconnected"}` |

Any method other than the one shown returns `405`. The beacon has exactly three modes; there is no
colour, speed or brightness. The tray binds `127.0.0.1:1337` by default — the README tells the
user to bind it to a LAN address for Home Assistant to reach it.

## 4. What the owner sees in Home Assistant

**Adding a beacon:** Settings → Devices & services → Add integration → BlinkyBeacon → host, port
(default 1337), name (default "BlinkyBeacon"). The form checks `GET /status` before saving and
says "cannot connect" if the tray does not answer. The same `host:port` cannot be added twice. A
**reconfigure** step changes host and port later (a tray PC's address can change).

**The device:** named as typed, with a link to the tray's own settings page
(`http://host:port/settings`).

**Entities per device**
- **Light** (named after the device): on/off, effects `spin` and `flash`. On = spinning or
  flashing; the effect shows which. Turning it on with no effect spins (or keeps the current
  effect if already on); off stops. Available when the tray answers and its USB light is plugged
  in.
- **USB connected** (binary sensor, connectivity): whether the tray sees its USB light. Available
  when the tray answers.
- When the tray does not answer, both are unavailable.

**Actions** (`blinkybeacon.spin`, `blinkybeacon.flash`, `blinkybeacon.stop`)
- Field `device_id`: one or more BlinkyBeacon devices (device picker filtered to this
  integration).
- Field `duration` (spin and flash only, optional): seconds, 1–3600. After that many seconds the
  integration sends `/stop`.
- If a beacon's tray is unreachable or its light is unplugged, the action **raises an error** that
  names the beacon, and the automation trace shows it. With several beacons, every beacon is
  tried and the error lists the ones that failed.

**Why actions target devices, not the light entity:** Home Assistant silently skips unavailable
entities in entity-targeted actions (`homeassistant/helpers/service.py`, `entity_service_call`
filters `e.available`; only a log warning). Targeting the device lets the integration attempt the
call and raise. The standard `light.turn_on/off` still works for dashboards and quick use; the
README tells automation writers to prefer the BlinkyBeacon actions.

## 5. Behaviour rules

- **Polling:** `GET /status` every 5 s per beacon, so changes made from the tray menu or the
  Companion module show up. A successful command updates the state at once from its reply, without
  waiting for the next poll.
- **Duration stop:** one pending stop per beacon. Any newer command to that beacon through this
  integration (an action, or the light) cancels it, so a second press within the window is not cut
  short. A command from outside HA (tray menu, Companion) does not cancel it — documented in the
  README. If the timed stop itself fails, it is logged as a warning (there is no caller to raise
  to). Unloading the integration (an HA restart, a reload, removing the beacon) with a stop
  pending sends that stop at once, best effort, so a timed spin never outlives HA.
- **Errors:** connection error or timeout (10 s) → "cannot reach the tray at host:port"; `503` →
  "the beacon light is not plugged in"; any other non-200 or a malformed reply → "unexpected reply".
  These are translated `HomeAssistantError`s; an unknown device id is a `ServiceValidationError`.
- **A tray down at startup:** the first `GET /status` failing makes setup retry later (HA's
  `ConfigEntryNotReady`). An action aimed at a beacon that is not loaded yet raises the same
  "cannot reach" error, never a silent skip. After a `503` the integration asks for a fresh poll,
  so the light and sensor catch up at once.

## 6. How it is made

- Python, the standard custom-integration layout under `custom_components/blinkybeacon/`:
  `manifest.json`, `__init__.py` (setup, unload, action registration), `api.py` (async client on
  HA's shared aiohttp session), `coordinator.py` (`DataUpdateCoordinator`), `entity.py`,
  `light.py`, `binary_sensor.py`, `config_flow.py`, `services.yaml`, `icons.json`, `strings.json`
  and `translations/en.json`.
- `manifest.json`: `iot_class: local_polling`, `integration_type: device`, `config_flow: true`, no
  extra requirements (aiohttp ships with HA), `codeowners: ["@clovisd"]`, version `0.1.0`.
- `hacs.json` with a minimum HA version of 2025.1.0; tested on 2026.10.4.
- Tests: `pytest-homeassistant-custom-component` (pins HA 2026.10.4, Python 3.14) with
  `aioclient_mock` standing in for the tray. Every behaviour above has a test.
- CI on GitHub Actions: hassfest, HACS validation (brands check ignored — the integration is not
  in `home-assistant/brands`), and the test suite.
- MIT licence, matching blinkybeacon-web. README covers: what it is, the tray setup (bind to a LAN
  address, Windows firewall, the open control routes on `main`), HACS install, adding a beacon,
  the entities, the actions with a button-to-beacon example automation, and the known limits.
- Shipping: public GitHub repo `clovisd/blinkybeacon-hassio` (matching blinkybeacon-web and the
  Companion module, both public; HACS needs a public repo), with a description and topics, tag
  `v0.1.0` and a GitHub release.

## 7. Calls made without the owner

These were my calls; the owner can change any of them.

- The beacon as a **light** with `spin`/`flash` effects, plus a USB connected sensor.
- Actions target **devices** and fail loudly (reason in §4).
- 5 s polling, 10 s request timeout, 1–3600 s duration range.
- Minimum HA version 2025.1.0 in `hacs.json`.
- Commit author `clovisd <clovisdelmotte@gmail.com>`, as in blinkybeacon-web's history.
- No row in blinkybeacon-web's `ROADMAP-STAGES.md` — this is its own repository; the owner can
  add one if it should be tracked there.

## 8. Left to the builder

File-internal structure, test organisation, exact wording of strings, and CI job layout.
