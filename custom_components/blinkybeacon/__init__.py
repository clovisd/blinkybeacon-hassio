"""The BlinkyBeacon integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import BlinkyBeaconClient
from .const import DOMAIN
from .coordinator import BlinkyBeaconConfigEntry, BlinkyBeaconCoordinator
from .services import async_setup_services

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.LIGHT]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions once, for every beacon."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: BlinkyBeaconConfigEntry) -> bool:
    """Set up a beacon; retried later if its tray does not answer."""
    client = BlinkyBeaconClient(
        async_get_clientsession(hass), entry.data[CONF_HOST], entry.data[CONF_PORT]
    )
    coordinator = BlinkyBeaconCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    async def _async_on_stop(_event: Event) -> None:
        # HA does not unload entries when it shuts down.
        await coordinator.async_shutdown_stop()

    entry.async_on_unload(hass.bus.async_listen(EVENT_HOMEASSISTANT_STOP, _async_on_stop))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BlinkyBeaconConfigEntry) -> bool:
    """Unload a beacon, first sending any pending timed stop."""
    await entry.runtime_data.async_shutdown_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
