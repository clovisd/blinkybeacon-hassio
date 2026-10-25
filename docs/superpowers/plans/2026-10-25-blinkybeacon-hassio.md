# blinkybeacon-hassio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A HACS-installable Home Assistant custom integration that drives BlinkyBeacon trays over their HTTP API, as devices with a light, a USB-connected sensor, and spin/flash/stop actions that fail visibly.

**Architecture:** One config entry per tray (`host:port`). A `DataUpdateCoordinator` polls `GET /status` every 5 s and owns command sending and the timed stop; the light and binary sensor read it. Domain-level actions take device ids, resolve them to config entries, and raise translated errors when a beacon does not answer.

**Tech Stack:** Python 3.14, Home Assistant 2026.10.4, aiohttp (HA's shared session), voluptuous, `pytest-homeassistant-custom-component==0.13.375`.

**Spec:** `docs/superpowers/specs/2026-10-25-blinkybeacon-hassio-design.md`

## Global Constraints

- Domain `blinkybeacon`; integration name `BlinkyBeacon`; version `0.1.0`; `codeowners: ["@clovisd"]`.
- `iot_class: local_polling`, `integration_type: device`, `config_flow: true`, `requirements: []`.
- Default port `1337`, default name `BlinkyBeacon`, poll interval 5 s, request timeout 10 s, duration 1–3600 s.
- Tray states are exactly `spin`, `flash`, `idle`; commands are `POST /spin`, `/flash`, `/stop`; status is `GET /status`.
- `hacs.json` minimum HA `2025.1.0`; tested on 2026.10.4.
- Every user-facing string lives in `strings.json` and an identical `translations/en.json`.
- Commands run with `.venv/bin/pytest` from the repo root.

## Review Focus

- A host typed as a URL (`http://192.168.1.50:1337/`) — the form strips the scheme and trailing slash and uses an embedded port; anything else with `/` is `invalid_host`. Test in Task 2.
- Something else answers on that port with `200` and an HTML page — `unexpected reply`, never a crash; the form says `invalid_reply`. Tests in Tasks 1 and 2.
- A future tray reports a state this version does not know (e.g. `test_flash`) — light on, effect `None`, no exception. Test in Task 4.
- HA restarts or the entry unloads during a timed spin — the pending stop is sent at once. Test in Task 5.
- A port outside 1–65535 — the form schema rejects it. Test in Task 2.

---

### Task 1: Scaffold and tray API client

**Files:**
- Create: `pyproject.toml`, `custom_components/__init__.py` (empty), `custom_components/blinkybeacon/__init__.py` (docstring only for now), `custom_components/blinkybeacon/manifest.json`, `custom_components/blinkybeacon/const.py`, `custom_components/blinkybeacon/api.py`
- Test: `tests/__init__.py`, `tests/conftest.py`, `tests/test_api.py`

**Interfaces:**
- Produces (`const.py`): `DOMAIN = "blinkybeacon"`, `DEFAULT_PORT = 1337`, `DEFAULT_NAME = "BlinkyBeacon"`, `SCAN_INTERVAL = timedelta(seconds=5)`, `REQUEST_TIMEOUT = 10`, `STATE_SPIN = "spin"`, `STATE_FLASH = "flash"`, `STATE_IDLE = "idle"`, `MIN_DURATION = 1`, `MAX_DURATION = 3600`.
- Produces (`api.py`):
  - `@dataclass(frozen=True) class BeaconStatus: state: str; connected: bool`
  - `class BlinkyBeaconError(Exception)`; subclasses `BlinkyBeaconConnectionError` (unreachable/timeout), `BlinkyBeaconNotConnectedError` (503), `BlinkyBeaconResponseError` (other status, non-JSON, wrong shape).
  - `class BlinkyBeaconClient(session: aiohttp.ClientSession, host: str, port: int)` with `base_url: str` (`http://host:port`, IPv6 literal bracketed via `yarl.URL.build`), `async status() -> BeaconStatus`, `async spin() -> BeaconStatus`, `async flash() -> BeaconStatus`, `async stop() -> BeaconStatus`.
- Produces (`tests/conftest.py`): autouse fixture enabling custom integrations; `HOST = "192.0.2.10"`, `PORT = 1337`, `BASE = "http://192.0.2.10:1337"`; fixture `mock_config_entry` → `MockConfigEntry(domain=DOMAIN, title="Home beacon", data={"host": HOST, "port": PORT}, unique_id="192.0.2.10:1337")`; helper `status_json(state="idle", connected=True) -> dict`.

- [ ] **Step 1: Write `pyproject.toml`** with `[tool.pytest.ini_options] asyncio_mode = "auto"`, `testpaths = ["tests"]`, and `manifest.json` per Global Constraints (`documentation`/`issue_tracker` → `https://github.com/clovisd/blinkybeacon-hassio`).

- [ ] **Step 2: Write the failing tests in `tests/test_api.py`** (each builds a client on `async_get_clientsession(hass)` and registers `aioclient_mock` responses):
  - `test_status_parses_reply`: GET `BASE/status` → `{"state":"spin","connected":true}` ⇒ `BeaconStatus("spin", True)`.
  - `test_commands_post_and_parse` (parametrised spin/flash/stop): POST `BASE/<cmd>` → `200` ⇒ returned state matches; `aioclient_mock.mock_calls[0][0] == "POST"`.
  - `test_503_raises_not_connected`: POST `/spin` → `503 {"error":"beacon not connected"}` ⇒ `BlinkyBeaconNotConnectedError`.
  - `test_unreachable_raises_connection_error` (parametrised `exc=aiohttp.ClientError()`, `exc=TimeoutError()`) ⇒ `BlinkyBeaconConnectionError`.
  - `test_html_reply_raises_response_error`: GET `/status` → `200`, `text="<html>router</html>"` ⇒ `BlinkyBeaconResponseError`.
  - `test_wrong_shape_raises_response_error`: `200 {"state": 3}` ⇒ `BlinkyBeaconResponseError`.
  - `test_other_status_raises_response_error`: `500` ⇒ `BlinkyBeaconResponseError`.
  - `test_ipv6_base_url`: host `"fd00::5"` ⇒ `base_url == "http://[fd00::5]:1337"`.

- [ ] **Step 3: Run** `.venv/bin/pytest tests/test_api.py -q` — expect collection errors / failures (no `api.py`).

- [ ] **Step 4: Implement `api.py`** — one private `_request(method, path) -> BeaconStatus` using `asyncio.timeout(REQUEST_TIMEOUT)`; read JSON with `content_type=None` and catch decode errors; `state` must be `str` and `connected` `bool`.

- [ ] **Step 5: Run** `.venv/bin/pytest tests/test_api.py -q` — expect all pass.

- [ ] **Step 6: Commit** — `feat: the tray API client and the integration scaffold`.

### Task 2: Config flow (add and reconfigure)

**Files:**
- Create: `custom_components/blinkybeacon/config_flow.py`, `custom_components/blinkybeacon/strings.json`, `custom_components/blinkybeacon/translations/en.json`
- Modify: `custom_components/blinkybeacon/__init__.py` — minimal `async_setup_entry` returning `True` and `async_unload_entry` returning `True`, so a created entry loads (replaced in Task 3).
- Test: `tests/test_config_flow.py`

**Interfaces:**
- Consumes: `BlinkyBeaconClient`, the error classes, `DEFAULT_PORT`, `DEFAULT_NAME`.
- Produces: `BlinkyBeaconConfigFlow` (`VERSION = 1`); entry `data = {"host": str, "port": int}`, `title = name`, `unique_id = f"{host}:{port}".lower()`. Form field keys `host`, `port`, `name` (`CONF_HOST`, `CONF_PORT`, `CONF_NAME`). Error keys `cannot_connect`, `invalid_reply`, `invalid_host`; abort keys `already_configured`, `reconfigure_successful`.
- Produces: `normalize_host(raw: str, port: int) -> tuple[str, int]` in `config_flow.py` — strips whitespace, a leading `http://`/`https://` and trailing `/`; a remaining `host:port` (not an IPv6 literal) splits off the port; raises `ValueError` if `/` remains or the host is empty.

- [ ] **Step 1: Write the failing tests:**
  - `test_user_flow_creates_entry`: status `200 idle` ⇒ `CREATE_ENTRY`, title `"Home beacon"`, data `{"host": HOST, "port": 1337}`, `unique_id == "192.0.2.10:1337"`.
  - `test_user_flow_cannot_connect` (`exc=ClientError()`) ⇒ form with `errors == {"base": "cannot_connect"}`; then fixing the mock and resubmitting creates the entry.
  - `test_user_flow_invalid_reply` (HTML body) ⇒ `{"base": "invalid_reply"}`.
  - `test_user_flow_url_typed_as_host`: host `"http://192.0.2.10:1338/"`, port 1337 ⇒ entry data `{"host": HOST, "port": 1338}`.
  - `test_user_flow_invalid_host`: host `"192.0.2.10/settings"` ⇒ `{"host": "invalid_host"}`.
  - `test_user_flow_port_out_of_range`: port `70000` ⇒ `pytest.raises(InvalidData)` from `async_configure`.
  - `test_user_flow_already_configured`: `mock_config_entry` added first ⇒ abort `already_configured`.
  - `test_reconfigure_updates_address`: with the entry loaded, reconfigure to `192.0.2.11` ⇒ abort `reconfigure_successful`, entry data host `192.0.2.11`, unique id updated.
  - `test_reconfigure_to_existing_address_aborts`: a second entry at `192.0.2.11:1337` ⇒ abort `already_configured`.

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_config_flow.py -q` — expect failures.

- [ ] **Step 3: Implement** `async_step_user` and `async_step_reconfigure` sharing one validate helper; reconfigure shows host and port only, uses `_get_reconfigure_entry()`, `_async_abort_entries_match` for the duplicate and `async_update_reload_and_abort(entry, unique_id=…, data_updates=…)`. Port field: `vol.All(vol.Coerce(int), vol.Range(min=1, max=65535))`. Strings: step titles "Add a BlinkyBeacon" / "Change the tray's address", field descriptions telling the user the tray must listen on a LAN address.

- [ ] **Step 4: Run** `.venv/bin/pytest tests/test_config_flow.py -q` — expect all pass.

- [ ] **Step 5: Commit** — `feat: add and reconfigure a beacon from the UI`.

### Task 3: Coordinator, setup and the USB connected sensor

**Files:**
- Create: `custom_components/blinkybeacon/coordinator.py`, `custom_components/blinkybeacon/entity.py`, `custom_components/blinkybeacon/binary_sensor.py`
- Modify: `custom_components/blinkybeacon/__init__.py`, `strings.json`, `translations/en.json`
- Test: `tests/test_init.py`, `tests/test_binary_sensor.py`

**Interfaces:**
- Produces (`coordinator.py`):
  - `type BlinkyBeaconConfigEntry = ConfigEntry[BlinkyBeaconCoordinator]`
  - `class BlinkyBeaconCoordinator(DataUpdateCoordinator[BeaconStatus])`, `__init__(hass, entry, client)`, attribute `client`, `update_interval=SCAN_INTERVAL`. `_async_update_data` raises `UpdateFailed` on any `BlinkyBeaconError`.
  - `async async_command(command: str, duration: int | None = None) -> None` — `command` in `{"spin","flash","stop"}`. Cancels the pending stop; sends; on success `async_set_updated_data(status)` and, if `duration`, schedules the stop with `async_call_later`. Raises `HomeAssistantError(translation_domain=DOMAIN, translation_key=…, translation_placeholders={"name": entry.title, "address": f"{host}:{port}"})` with key `cannot_reach` (connection error), `not_plugged_in` (503, after scheduling `async_request_refresh()`), `unexpected_reply` (response error).
  - `async async_shutdown_stop() -> None` — if a stop is pending, cancel the timer and send `stop` now; log a warning on failure.
  - `def address(self) -> str` property → `"host:port"`.
- Produces (`entity.py`): `class BlinkyBeaconEntity(CoordinatorEntity[BlinkyBeaconCoordinator])`, `_attr_has_entity_name = True`, `device_info` with identifiers `{(DOMAIN, entry.entry_id)}`, name `entry.title`, manufacturer `"BlinkyBeacon"`, model `"blinkybeacon-tray"`, `configuration_url = f"{client.base_url}/settings"`.
- Produces (`__init__.py`): `PLATFORMS = [Platform.BINARY_SENSOR, Platform.LIGHT]` (light added in Task 4 — list only `BINARY_SENSOR` until then); `async_setup_entry` builds the client on `async_get_clientsession(hass)`, `await coordinator.async_config_entry_first_refresh()`, sets `entry.runtime_data`; `async_unload_entry` unloads platforms then `await entry.runtime_data.async_shutdown_stop()`.
- Binary sensor: unique id `f"{entry_id}_usb_connected"`, translation key `usb_connected` ("USB connected"), device class `CONNECTIVITY`, `EntityCategory.DIAGNOSTIC`, `is_on = data.connected`.

- [ ] **Step 1: Write the failing tests:**
  - `test_setup_and_unload`: status `200 idle connected` ⇒ entry `LOADED`; unload ⇒ `NOT_LOADED`.
  - `test_setup_retries_when_tray_down` (`exc=ClientError()`) ⇒ entry state `SETUP_RETRY`.
  - `test_device_registered`: device with identifiers `{("blinkybeacon", entry.entry_id)}`, name `"Home beacon"`, `configuration_url == "http://192.0.2.10:1337/settings"`.
  - `test_usb_connected_on_off`: `binary_sensor.home_beacon_usb_connected` is `on`; next poll (`freezer.tick(5)` + `async_fire_time_changed`) returns `connected: false` ⇒ `off`.
  - `test_usb_sensor_unavailable_when_tray_unreachable`: next poll raises ⇒ `unavailable`; recovers to `on` on the following poll.

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_init.py tests/test_binary_sensor.py -q` — expect failures.

- [ ] **Step 3: Implement** the coordinator, base entity, binary sensor and `__init__.py` wiring per Interfaces.

- [ ] **Step 4: Run** `.venv/bin/pytest -q` — expect all pass.

- [ ] **Step 5: Commit** — `feat: poll each tray and show whether its USB light is plugged in`.

### Task 4: The light

**Files:**
- Create: `custom_components/blinkybeacon/light.py`
- Modify: `custom_components/blinkybeacon/__init__.py` (`PLATFORMS` gains `Platform.LIGHT`)
- Test: `tests/test_light.py`

**Interfaces:**
- Consumes: `BlinkyBeaconEntity`, `BlinkyBeaconCoordinator.async_command`.
- Produces: `BlinkyBeaconLight` — `_attr_name = None` (entity id `light.home_beacon`), unique id `f"{entry_id}_light"`, `ColorMode.ONOFF` only, `LightEntityFeature.EFFECT`, `effect_list = ["spin", "flash"]`. `available` = coordinator available and `data.connected`. `is_on = data.state != "idle"`. `effect = data.state if data.state in effect_list else None`. `turn_on(effect=None)`: given effect, else current effect if on, else `spin`. `turn_off` → `stop`.

- [ ] **Step 1: Write the failing tests:**
  - `test_light_reflects_state` (parametrised): `idle` ⇒ `off`; `spin` ⇒ `on`, `effect == "spin"`; `flash` ⇒ `on`, `effect == "flash"`.
  - `test_light_unknown_state_is_on_without_effect`: `test_flash` ⇒ `on`, `effect is None`, no error logged.
  - `test_turn_on_default_spins`: `light.turn_on` ⇒ POST `/spin`; state updates to `on`/`spin` before any poll.
  - `test_turn_on_with_flash_effect` ⇒ POST `/flash`.
  - `test_turn_on_while_flashing_keeps_flash` ⇒ POST `/flash`.
  - `test_turn_off_stops` ⇒ POST `/stop`, state `off`.
  - `test_light_unavailable_when_unplugged`: `connected: false` ⇒ `unavailable`.
  - `test_turn_on_503_raises`: POST `/spin` → `503` ⇒ `pytest.raises(HomeAssistantError)` with `translation_key == "not_plugged_in"`.

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_light.py -q` — expect failures.

- [ ] **Step 3: Implement** `light.py` per Interfaces.

- [ ] **Step 4: Run** `.venv/bin/pytest -q` — expect all pass.

- [ ] **Step 5: Commit** — `feat: each beacon is a light with spin and flash effects`.

### Task 5: Actions (spin, flash, stop) with the timed stop

**Files:**
- Create: `custom_components/blinkybeacon/services.py`, `custom_components/blinkybeacon/services.yaml`, `custom_components/blinkybeacon/icons.json`
- Modify: `custom_components/blinkybeacon/__init__.py` (`CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)`; `async_setup` calls `async_setup_services(hass)`), `strings.json`, `translations/en.json`
- Test: `tests/test_services.py`

**Interfaces:**
- Consumes: `BlinkyBeaconCoordinator.async_command`, `BlinkyBeaconConfigEntry`.
- Produces: `async_setup_services(hass: HomeAssistant) -> None` registering `spin`, `flash` (fields `device_id` — `vol.All(cv.ensure_list, [cv.string])`, required; `duration` — `vol.All(vol.Coerce(int), vol.Range(min=1, max=3600))`, optional) and `stop` (`device_id` only).
- Device resolution: unknown device, or a device with no `blinkybeacon` config entry ⇒ `ServiceValidationError(translation_key="unknown_device", placeholders {"device_id"})`. Entry not `LOADED` ⇒ `HomeAssistantError(translation_key="cannot_reach")` with its title and address.
- One device: its error propagates as is. Several: every one is tried; failures raise `HomeAssistantError(translation_key="commands_failed", placeholders {"names": "Home beacon, Away beacon"})`.
- `services.yaml`: `device_id` uses `selector: device: {integration: blinkybeacon, multiple: true}`; `duration` uses `selector: number: {min: 1, max: 3600, unit_of_measurement: s, mode: box}`. Icons: spin `mdi:rotate-right`, flash `mdi:alarm-light`, stop `mdi:stop-circle-outline`.

- [ ] **Step 1: Write the failing tests** (two entries, "Home beacon" `192.0.2.10` and "Away beacon" `192.0.2.11`, where needed):
  - `test_spin_action_spins` ⇒ POST `http://192.0.2.10:1337/spin`, `light.home_beacon` on/spin.
  - `test_flash_and_stop_actions` ⇒ POST `/flash`, then POST `/stop`.
  - `test_duration_sends_stop_after`: spin with `duration: 10`; at 9 s no `/stop`; at 10 s one POST `/stop`.
  - `test_new_command_cancels_pending_stop`: spin `duration: 10`; at 5 s spin `duration: 10` again; at 11 s no `/stop`; at 15 s one `/stop`.
  - `test_light_turn_off_cancels_pending_stop`: spin `duration: 10`, `light.turn_off` ⇒ exactly one `/stop` by 20 s.
  - `test_timed_stop_failure_logs_warning`: `/stop` raises `ClientError` at the deadline ⇒ warning in `caplog`, no exception.
  - `test_unload_sends_pending_stop`: spin `duration: 60`, unload the entry ⇒ one POST `/stop` before unload returns; none later.
  - `test_unreachable_raises_cannot_reach`: POST `/spin` raises ⇒ `HomeAssistantError`, `translation_key == "cannot_reach"`.
  - `test_unplugged_raises_not_plugged_in`: `503` ⇒ `translation_key == "not_plugged_in"`.
  - `test_unknown_device_raises_validation`: a device from another integration (`MockConfigEntry(domain="zha")`) ⇒ `ServiceValidationError`, `translation_key == "unknown_device"`.
  - `test_not_loaded_entry_raises_cannot_reach`: entry in `SETUP_RETRY` ⇒ `translation_key == "cannot_reach"`.
  - `test_two_beacons_one_fails`: home OK, away `503` ⇒ home's `/spin` was sent, `translation_key == "commands_failed"`, placeholder names `"Away beacon"`.
  - `test_duration_out_of_range` (`0`, `3601`) ⇒ `vol.Invalid` / `MultipleInvalid`.

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_services.py -q` — expect failures.

- [ ] **Step 3: Implement** `services.py` and the timer pieces of the coordinator the tests need (the timer callback calls `async_command("stop")` inside `try/except HomeAssistantError` → `_LOGGER.warning`).

- [ ] **Step 4: Run** `.venv/bin/pytest -q` — expect all pass.

- [ ] **Step 5: Commit** — `feat: spin, flash and stop actions that name the beacon that did not answer`.

### Task 6: Packaging, docs and CI

**Files:**
- Create: `hacs.json` (`{"name": "BlinkyBeacon", "homeassistant": "2025.1.0", "render_readme": true}`), `LICENSE` (MIT, 2026, clovisd), `README.md`, `requirements_test.txt` (`pytest-homeassistant-custom-component==0.13.375`), `.github/workflows/validate.yml`

- [ ] **Step 1: Write `README.md`** — what it is; tray setup (bind the tray to `0.0.0.0` or its LAN IP in its settings page, allow the port through Windows Firewall, `main`'s control routes take no token so anyone on the LAN can trigger them); install via HACS custom repository; adding a beacon; entities; actions with YAML for spin-with-duration and a home/away button example (short press → spin home 10 s, long press → flash home 10 s; the trigger picked from the button's device triggers in the editor); why automations should use the BlinkyBeacon actions over `light.turn_on`; limits (one beacon per tray, no token, external commands do not cancel a timed stop); development (`uv venv --python 3.14`, `pip install -r requirements_test.txt`, `pytest`).

- [ ] **Step 2: Write `.github/workflows/validate.yml`** — on push and pull request: `hassfest` (`home-assistant/actions/hassfest@master`), `hacs` (`hacs/action@main`, `category: integration`, `ignore: brands`), `tests` (`actions/setup-python` 3.14, install `requirements_test.txt`, `pytest -q`).

- [ ] **Step 3: Run** `.venv/bin/pytest -q` and `python3 -c` JSON-parse every `*.json` under `custom_components` and `hacs.json`; check `strings.json` and `translations/en.json` are identical (`cmp`). Expected: all pass, `cmp` silent.

- [ ] **Step 4: Commit** — `docs: README, HACS metadata, licence and CI`.

### Task 7: Ship

- [ ] **Step 1:** Whole-branch review against the spec (one reviewer pass); fix findings; tests green.
- [ ] **Step 2:** `gh repo create clovisd/blinkybeacon-hassio --public --description "Home Assistant integration for BlinkyBeacon trays" --source . --push`; set topics `home-assistant`, `hacs`, `homeassistant-integration`, `blinkybeacon`.
- [ ] **Step 3:** Watch the CI run; fix and push until hassfest, HACS and tests are green.
- [ ] **Step 4:** Tag `v0.1.0`, push the tag, `gh release create v0.1.0` with notes. Expected: HACS can add `https://github.com/clovisd/blinkybeacon-hassio` as a custom integration repository.
