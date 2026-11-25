"""Polls one beacon for its state and sends it commands."""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    BeaconStatus,
    BlinkyBeaconClient,
    BlinkyBeaconConnectionError,
    BlinkyBeaconError,
    BlinkyBeaconNotConnectedError,
)
from .const import (
    CONF_USB_PORT,
    DOMAIN,
    SCAN_INTERVAL,
    TIMED_STOP_RETRIES,
    TIMED_STOP_RETRY_INTERVAL,
)
from .usb_beacon import UsbBeacon

_LOGGER = logging.getLogger(__name__)

type BlinkyBeaconConfigEntry = ConfigEntry[BlinkyBeaconCoordinator]

USB_ERRORS = {"cannot_reach": "usb_not_loaded", "not_plugged_in": "usb_not_plugged_in"}

ISSUE_TIMED_STOP_FAILED = "timed_stop_failed"


def timed_stop_issue_id(entry_id: str) -> str:
    """The ID of the notice that an entry's beacon did not take its timed stop."""
    return f"{ISSUE_TIMED_STOP_FAILED}_{entry_id}"


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
        # One command at a time: the answers come in the order the commands were
        # sent, so an older command's late answer cannot undo a newer one.
        self._command_lock = asyncio.Lock()
        self._commands_taken = 0
        self._timed_stop_issue = timed_stop_issue_id(entry.entry_id)
        entry.async_on_unload(self._async_clear_timed_stop_issue)

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
        A command that succeeds also clears the notice of a timed stop not taken.
        A command sent while another is waiting for its answer waits its turn.
        """
        async with self._command_lock:
            await self._async_send(command, duration)

    async def _async_send(self, command: str, duration: int | None = None) -> None:
        """Send one command; the command lock must be held."""
        try:
            status = await getattr(self.client, command)()
        except BlinkyBeaconConnectionError as err:
            raise self.error("cannot_reach") from err
        except BlinkyBeaconNotConnectedError as err:
            await self.async_request_refresh()
            raise self.error("not_plugged_in") from err
        except BlinkyBeaconError as err:
            raise self.error("unexpected_reply") from err
        self._commands_taken += 1
        self._async_cancel_timed_stop()
        self._async_clear_timed_stop_issue()
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

    @callback
    def _async_clear_timed_stop_issue(self) -> None:
        ir.async_delete_issue(self.hass, DOMAIN, self._timed_stop_issue)

    async def _async_timed_stop(
        self, _now: datetime, retries_left: int = TIMED_STOP_RETRIES
    ) -> None:
        """Send the stop a timed command ends with.

        One the beacon does not take is sent again a few seconds later, a
        bounded number of times, as a pending timed stop: a newer command
        replaces it. After the last, a notice names the beacon, which may still
        be on. A stop that comes due while a newer command waits for its answer
        is dropped once that command is taken.
        """
        self._cancel_timed_stop = None
        taken = self._commands_taken
        async with self._command_lock:
            if self._commands_taken != taken:
                return
            await self._async_send_timed_stop(retries_left)

    async def _async_send_timed_stop(self, retries_left: int) -> None:
        try:
            await self._async_send("stop")
        except HomeAssistantError as err:
            if retries_left > 0:
                _LOGGER.warning(
                    "Could not stop %s at the end of its timed command; trying "
                    "again in %s s: %s",
                    self.config_entry.title,
                    TIMED_STOP_RETRY_INTERVAL,
                    err,
                )

                async def _async_retry(now: datetime) -> None:
                    await self._async_timed_stop(now, retries_left - 1)

                self._cancel_timed_stop = async_call_later(
                    self.hass, TIMED_STOP_RETRY_INTERVAL, _async_retry
                )
                return
            _LOGGER.error(
                "Could not stop %s at the end of its timed command after %s "
                "tries; it may still be on: %s",
                self.config_entry.title,
                TIMED_STOP_RETRIES + 1,
                err,
            )
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._timed_stop_issue,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key=ISSUE_TIMED_STOP_FAILED,
                translation_placeholders={
                    "name": self.config_entry.title,
                    "address": self.address,
                    "tries": str(TIMED_STOP_RETRIES + 1),
                },
            )

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
            translation_key=USB_ERRORS.get(key, "usb_not_plugged_in"),
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
