"""Polls one tray for its state and sends it commands."""

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
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

type BlinkyBeaconConfigEntry = ConfigEntry[BlinkyBeaconCoordinator]


class BlinkyBeaconCoordinator(DataUpdateCoordinator[BeaconStatus]):
    """Holds one tray's last known state."""

    config_entry: BlinkyBeaconConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: BlinkyBeaconConfigEntry,
        client: BlinkyBeaconClient,
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
        """The tray's host:port, for messages."""
        return f"{self.config_entry.data[CONF_HOST]}:{self.config_entry.data[CONF_PORT]}"

    async def _async_update_data(self) -> BeaconStatus:
        try:
            return await self.client.status()
        except BlinkyBeaconError as err:
            raise UpdateFailed(f"{self.address} did not answer /status: {err!r}") from err

    async def async_command(self, command: str, duration: int | None = None) -> None:
        """Send spin, flash or stop; raise an error naming the beacon if it fails.

        Any command replaces a pending timed stop. With a duration, a stop follows
        that many seconds later.
        """
        self._async_cancel_timed_stop()
        try:
            status = await getattr(self.client, command)()
        except BlinkyBeaconConnectionError as err:
            raise self.error("cannot_reach") from err
        except BlinkyBeaconNotConnectedError as err:
            await self.async_request_refresh()
            raise self.error("not_plugged_in") from err
        except BlinkyBeaconError as err:
            raise self.error("unexpected_reply") from err
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
    """A translated error naming a beacon and its tray's address."""
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders={
            "name": entry.title,
            "address": f"{entry.data[CONF_HOST]}:{entry.data[CONF_PORT]}",
        },
    )
