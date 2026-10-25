"""The beacon as a light: on spins or flashes, off stops."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_EFFECT,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import STATE_FLASH, STATE_IDLE, STATE_SPIN
from .coordinator import BlinkyBeaconConfigEntry, BlinkyBeaconCoordinator
from .entity import BlinkyBeaconEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlinkyBeaconConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the beacon's light."""
    async_add_entities([BlinkyBeaconLight(entry.runtime_data)])


class BlinkyBeaconLight(BlinkyBeaconEntity, LightEntity):
    """On while spinning or flashing; the effect says which."""

    _attr_name = None
    _attr_translation_key = "beacon"
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = [STATE_SPIN, STATE_FLASH]

    def __init__(self, coordinator: BlinkyBeaconCoordinator) -> None:
        super().__init__(coordinator, "light")

    @property
    def available(self) -> bool:
        """Available while the tray answers and its USB light is plugged in."""
        return super().available and self.coordinator.data.connected

    @property
    def is_on(self) -> bool:
        """On for any state but idle, including ones a newer tray may add."""
        return self.coordinator.data.state != STATE_IDLE

    @property
    def effect(self) -> str | None:
        """Spin or flash, or None when off or in a state this version does not know."""
        state = self.coordinator.data.state
        return state if state in self._attr_effect_list else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Spin, flash, or keep the current effect if already on."""
        effect = kwargs.get(ATTR_EFFECT) or self.effect or STATE_SPIN
        await self.coordinator.async_command(effect)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the beacon."""
        await self.coordinator.async_command("stop")
