"""Polls one tray for its state."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BeaconStatus, BlinkyBeaconClient, BlinkyBeaconError
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

    @property
    def address(self) -> str:
        """The tray's host:port, for messages."""
        return f"{self.config_entry.data[CONF_HOST]}:{self.config_entry.data[CONF_PORT]}"

    async def _async_update_data(self) -> BeaconStatus:
        try:
            return await self.client.status()
        except BlinkyBeaconError as err:
            raise UpdateFailed(f"{self.address} did not answer /status: {err!r}") from err
