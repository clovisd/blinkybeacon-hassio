"""Whether the tray sees its USB beacon light."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BlinkyBeaconConfigEntry, BlinkyBeaconCoordinator
from .entity import BlinkyBeaconEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlinkyBeaconConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the USB connected sensor."""
    async_add_entities([BlinkyBeaconUsbConnected(entry.runtime_data)])


class BlinkyBeaconUsbConnected(BlinkyBeaconEntity, BinarySensorEntity):
    """On while the tray reports its USB light as connected."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "usb_connected"

    def __init__(self, coordinator: BlinkyBeaconCoordinator) -> None:
        super().__init__(coordinator, "usb_connected")

    @property
    def is_on(self) -> bool:
        """Whether the USB light is plugged in."""
        return self.coordinator.data.connected
