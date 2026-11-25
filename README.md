# BlinkyBeacon for Home Assistant

A Home Assistant integration for [BlinkyBeacon](https://github.com/clovisd/blinkybeacon-web):
the USB beacon light. A beacon plugged into a PC is driven through `blinkybeacon-tray` on that
PC; a beacon plugged straight into the Home Assistant machine is driven by the integration
itself, with no tray. Each beacon becomes a device in Home Assistant, so automations and
scripts can spin, flash and stop it — for example, a Zigbee button press that lights the
beacon of the team that pressed it.

The beacon has three modes: **spin**, **flash** and **stop**. It has no colour, speed or
brightness control.

## What you get

For each beacon (a tray at one `host:port`, or one USB port of the Home Assistant machine):

| Entity | What it shows |
|---|---|
| **Light** (named after the beacon) | On while spinning or flashing; the `spin` and `flash` effects say which. Turning it on with no effect spins; off stops. Unavailable while the USB light is unplugged. |
| **USB connected** (diagnostic) | Whether the tray sees its USB light, or whether Home Assistant can reach the beacon in its USB port. |

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
not cut short. Commands to one beacon are sent one at a time, in the order they were made: one
made while another waits for the beacon's answer waits its turn, so the last one made is the
one the beacon ends on. If the beacon does not take that stop, it is sent again 5 seconds
later, up to 3 more times, and the log says so; a newer command replaces those too. If the
last one is not taken either, **Settings → Repairs** names the beacon, which may still be on,
until the next command it takes.

If a beacon's tray does not answer, or its USB light is unplugged, the action **fails with an
error naming the beacon** (and, for a beacon plugged into Home Assistant, its USB port), and
the automation's trace shows it. When several beacons are
chosen, every one is tried and the error lists the ones that failed.

A tray's reply is read up to 1024 bytes (its own are under 100). A longer one is not the
tray's: it is refused, and an error shows at most 100 characters of a reply it cannot use.

**Who may call them.** A person signed in to Home Assistant may call these actions only for
beacons they may control, as for Home Assistant's own actions on entities: an administrator
and an ordinary user may, and a user of the read-only group may not. Such a user needs the
control permission on every entity of every beacon chosen; if one is missing, Home Assistant
refuses the whole call as unauthorized and no beacon gets a command. An automation or a
script it runs calls them as before, with no such check.

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

Settings → Devices & services → **Add integration** → **BlinkyBeacon**. When a beacon with no
name is plugged into the Home Assistant machine, the first step asks where the beacon is
plugged in: choose **Into a PC running blinkybeacon-tray** for a tray, or see
[Beacons plugged into Home Assistant](#beacons-plugged-into-home-assistant). Otherwise the
tray form opens straight away. For a tray, enter:

- **Host** — the tray PC's IP address or hostname. A pasted URL such as
  `http://192.168.1.50:1337/` is accepted.
- **Port** — `1337` unless you changed it.
- **Name** — for example `Home beacon`.

The form checks the tray answers before saving. Add each beacon the same way. If a tray PC's
address changes, use **Reconfigure** on the beacon's entry.

## Beacons plugged into Home Assistant

A beacon can also be plugged straight into a USB port of the machine running Home Assistant.
The integration drives it itself; no tray is needed. Several beacons can be plugged in at
once, each with its own name, for example one per team. On Home Assistant OS, Home
Assistant's own process can write the machine's `/dev/hidraw*` devices, which is what the
integration needs; another installation needs the same.

**Each beacon is known by the USB port it is plugged into**, because the beacons are
identical and carry no serial number. Keep each beacon in its port: label the ports or the
hub, and plug the beacons in the same way every time. A beacon plugged into a different port
is a new beacon to be named.

**Adding one.** While at least one BlinkyBeacon is set up and working, a beacon plugged into
a USB port that has no name yet is offered within about 10 seconds under Settings →
Devices & services, as *BlinkyBeacon found on USB port 1-1*. Select **Add**, confirm, then
name it. You can also add one by hand at any time: **Add integration** → **BlinkyBeacon** →
**Into this Home Assistant**, then pick its port from the list of ports holding a beacon
with no name. While you name it, the beacon flashes, so you can tell which one it is; it
stops when you submit, when you close a form you started by hand, and at the latest 2
minutes after the form was last shown. The port, such as `1-1` or `1-3.2` behind a hub, is
how Linux numbers the machine's USB ports.

**When a beacon is unplugged**, its light is unavailable and its **USB connected** sensor is
off, as for a tray whose light is unplugged, and an action aimed at it fails with an error
naming it and its port. A notice in Settings → System → **Repairs** says *Team A is missing
from USB port 1-1* (with your beacon's name). The same notice appears when the beacon is in
its port but Home Assistant is not allowed to open it (see above); the log names the error.
Plug it back into the same port and the notice clears by itself within about 10 seconds, the
beacon idle; its name, entities and automations are kept. A beacon plugged straight back in
(within about 5 seconds), or one write to it that fails while it stays in its port, does not
stop it: it is opened again and goes on spinning or flashing as it was, and the log says so. If the beacon is not coming back,
open the notice and submit to remove it.

Disabling, reloading or removing a beacon's entry stops the beacon.

## Troubleshooting

**A beacon on a tray stops by itself 1–2 seconds after it starts.** The tray's `dashboard`
build has a watcher that, while a dashboard URL and token are set in the tray's settings,
sets the beacon back to idle on each of its polls (every 2 seconds by default) when its
dashboard line has nothing live. Open `http://<pc-address>:1337/settings`: if the dashboard
URL and token are filled in, the watcher drives the light. Clear the URL or the token there,
or run the tray's `main` build, which has no watcher, to drive the beacon from Home
Assistant.

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
  yet; several beacons on one machine are supported when they are plugged into Home
  Assistant.
- A beacon plugged into Home Assistant is known only by its USB port; moving it to another
  port makes it a new beacon.
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
