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
from homeassistant.helpers.typing import DiscoveryInfoType
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
