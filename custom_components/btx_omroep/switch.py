"""Radio aan/uit."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import OmroepConfigEntry
from .entiteit import OmroepEntiteit


async def async_setup_entry(
    hass: HomeAssistant, entry: OmroepConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c = entry.runtime_data.coordinator
    async_add_entities([RadioSchakelaar(c, entry, "radio"), Muziekje(c, entry, "muziekje")])


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


class Muziekje(OmroepEntiteit, SwitchEntity, RestoreEntity):
    """Gong voor en na elke boodschap."""

    _attr_icon = "mdi:music-note"

    def __init__(self, coordinator, entry: OmroepConfigEntry, sleutel: str) -> None:
        super().__init__(coordinator, entry, sleutel)
        self._entry = entry

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (vorig := await self.async_get_last_state()) is not None and vorig.state in ("on", "off"):
            self._entry.runtime_data.instellingen["muziekje"] = vorig.state == "on"

    @property
    def is_on(self) -> bool:
        return self._entry.runtime_data.instellingen["muziekje"]

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._entry.runtime_data.instellingen["muziekje"] = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._entry.runtime_data.instellingen["muziekje"] = False
        self.async_write_ha_state()
