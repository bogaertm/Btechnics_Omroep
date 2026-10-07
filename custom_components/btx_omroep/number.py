"""Volume van de radio."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import OmroepConfigEntry
from .entiteit import OmroepEntiteit


async def async_setup_entry(
    hass: HomeAssistant, entry: OmroepConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([RadioVolume(entry.runtime_data.coordinator, entry, "volume")])


class RadioVolume(OmroepEntiteit, NumberEntity):
    _attr_icon = "mdi:volume-high"
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0
    _attr_native_step = 1

    @property
    def native_max_value(self) -> float:
        return (self.coordinator.data or {}).get("max_volume", 32)

    @property
    def native_value(self) -> float | None:
        return (self.coordinator.data or {}).get("volume")

    async def async_set_native_value(self, value: float) -> None:
        async with self.coordinator.lock:
            await self.coordinator.tuner.zet_volume(int(value))
        await self._na_actie()
