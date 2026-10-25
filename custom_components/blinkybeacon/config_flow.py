"""Add a BlinkyBeacon tray from the UI, and change its address later."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .api import BlinkyBeaconClient, BlinkyBeaconConnectionError, BlinkyBeaconError
from .const import DEFAULT_NAME, DEFAULT_PORT, DOMAIN

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
    """One flow per tray."""

    VERSION = 1

    async def async_step_user(
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
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Point an existing beacon at its tray's new address."""
        entry = self._get_reconfigure_entry()
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
