# BlinkyBeacon for Home Assistant

A Home Assistant integration for [BlinkyBeacon](https://github.com/clovisd/blinkybeacon-web):
the USB beacon light driven by `blinkybeacon-tray`. Each tray becomes a device in Home
Assistant, so automations and scripts can spin, flash and stop it — for example, a Zigbee
button press that lights the beacon of the team that pressed it.

The beacon has three modes: **spin**, **flash** and **stop**. It has no colour, speed or
brightness control.

## What you get

For each beacon (one tray, one `host:port`):

| Entity | What it shows |
|---|---|
| **Light** (named after the beacon) | On while spinning or flashing; the `spin` and `flash` effects say which. Turning it on with no effect spins; off stops. Unavailable while the USB light is unplugged. |
| **USB connected** (diagnostic) | Whether the tray sees its USB light. |

Both are unavailable while the tray does not answer. The integration reads the tray's state
every 5 seconds, so changes made from the tray menu or from Bitfocus Companion show up too.

### Actions

| Action | Fields |
|---|---|
| `blinkybeacon.spin` | `device_id` (one or more beacons), `duration` (optional, 1–3600 s) |
| `blinkybeacon.flash` | `device_id`, `duration` (optional, 1–3600 s) |
| `blinkybeacon.stop` | `device_id` |

With a `duration`, the beacon is stopped that many seconds later. Any newer command to that
beacon from Home Assistant replaces the pending stop, so a second press within the window is
not cut short.

If a beacon's tray does not answer, or its USB light is unplugged, the action **fails with an
error naming the beacon**, and the automation's trace shows it. When several beacons are
chosen, every one is tried and the error lists the ones that failed.

**Use these actions in automations rather than `light.turn_on`.** Home Assistant silently
skips an unavailable light in `light.turn_on`, so a beacon that is down would look like a
success. The BlinkyBeacon actions target the device and always report a failure.

## Setting up the tray

The tray listens on `127.0.0.1:1337` by default, which only the PC itself can reach. On each
PC with a beacon:

1. Tray menu → **Settings…** → set the bind address to `0.0.0.0` (or the PC's LAN address)
   and save.
2. Allow the tray through Windows Firewall on the port (Windows asks the first time it binds
   to the network; allow it on private networks).
3. Check from another machine: `curl http://<pc-address>:1337/status` should answer
   `{"state":"idle","connected":true}`.

Note: on the tray's `main` line (`v0.4.x`), `/spin`, `/flash` and `/stop` take no token, so
anything on the LAN that can reach the port can drive the beacon.

## Installing

Through [HACS](https://hacs.xyz/):

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/clovisd/blinkybeacon-hassio`
   with type **Integration**.
2. Find **BlinkyBeacon** in HACS, download it, and restart Home Assistant.

Or by hand: copy `custom_components/blinkybeacon` into your Home Assistant `config/custom_components/`
and restart.

## Adding a beacon

Settings → Devices & services → **Add integration** → **BlinkyBeacon**, then enter:

- **Host** — the tray PC's IP address or hostname. A pasted URL such as
  `http://192.168.1.50:1337/` is accepted.
- **Port** — `1337` unless you changed it.
- **Name** — for example `Home beacon`.

The form checks the tray answers before saving. Add each beacon the same way. If a tray PC's
address changes, use **Reconfigure** on the beacon's entry.

## Example: a team button

Short press spins the home beacon for 10 seconds; a long press flashes it for 10 seconds.
Build the triggers in the automation editor (**Add trigger → Device →** your button → its
short-press and long-press triggers), and give them the trigger IDs `short` and `long`
(⋮ → **Edit ID**). Then open the automation in YAML (⋮ → **Edit in YAML**) and replace its
`actions:` with:

```yaml
actions:
  - choose:
      - conditions:
          - condition: trigger
            id: short
        sequence:
          - action: blinkybeacon.spin
            data:
              device_id: <home beacon device id>
              duration: 10
      - conditions:
          - condition: trigger
            id: long
        sequence:
          - action: blinkybeacon.flash
            data:
              device_id: <home beacon device id>
              duration: 10
```

Copy the automation for the away button and the away beacon.

## Limits

- One beacon per tray. A tray driving several beacons (blinkybeacon-web S16) is not supported
  yet.
- No token on the control routes (blinkybeacon-web S17/S18) yet.
- A command sent from outside Home Assistant (the tray menu, Companion) does not cancel a
  pending timed stop.
- If Home Assistant shuts down or the beacon is removed during a timed spin, the stop is sent
  straight away.

## Development

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements_test.txt
.venv/bin/pytest -q
.venv/bin/ruff check custom_components tests  # after: uv pip install --python .venv/bin/python ruff==0.17.2
```

Tested on Home Assistant 2026.10.4.

## Licence

MIT — see [LICENSE](LICENSE).
