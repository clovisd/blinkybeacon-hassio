"""The base entity shared by a beacon's light and sensor."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import BlinkyBeaconClient
from .const import DOMAIN
from .coordinator import BlinkyBeaconCoordinator


class BlinkyBeaconEntity(CoordinatorEntity[BlinkyBeaconCoordinator]):
    """An entity of one beacon's device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BlinkyBeaconCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        if isinstance(client := coordinator.client, BlinkyBeaconClient):
            model, url = "blinkybeacon-tray", f"{client.base_url}/settings"
        else:
            model, url = "USB beacon", None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="BlinkyBeacon",
            model=model,
            configuration_url=url,
        )
