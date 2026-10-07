"""Radio aan/uit."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import OmroepConfigEntry
from .entiteit import OmroepEntiteit


async def async_setup_entry(
    hass: HomeAssistant, entry: OmroepConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([RadioSchakelaar(entry.runtime_data.coordinator, entry, "radio")])


class RadioSchakelaar(OmroepEntiteit, SwitchEntity):
    _attr_icon = "mdi:radio"

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.get("power") if self.coordinator.data else None

    async def _zet(self, aan: bool) -> None:
        # wacht tot een lopend bericht klaar is, anders klopt het herstel niet meer
        async with self.coordinator.lock:
            await self.coordinator.tuner.zet_power(aan)
        await self._na_actie()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._zet(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._zet(False)
