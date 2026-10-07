"""Tekstvelden: omroeptekst en naam om een tekst als boodschap op te slaan."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import OmroepConfigEntry
from .entiteit import OmroepEntiteit


async def async_setup_entry(
    hass: HomeAssistant, entry: OmroepConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c = entry.runtime_data.coordinator
    async_add_entities([OmroepTekst(c, entry, "tekst", 255, "mdi:text"), OmroepTekst(c, entry, "naam", 60, "mdi:tag")])


class OmroepTekst(OmroepEntiteit, TextEntity, RestoreEntity):
    def __init__(self, coordinator, entry: OmroepConfigEntry, sleutel: str, maximum: int, icoon: str) -> None:
        super().__init__(coordinator, entry, sleutel)
        self._entry = entry
        self._sleutel = sleutel
        self._attr_native_max = maximum
        self._attr_icon = icoon

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (vorig := await self.async_get_last_state()) is not None and vorig.state not in ("unknown", "unavailable"):
            self._entry.runtime_data.instellingen[self._sleutel] = vorig.state

    @property
    def native_value(self) -> str:
        return self._entry.runtime_data.instellingen.get(self._sleutel) or ""

    async def async_set_value(self, value: str) -> None:
        self._entry.runtime_data.instellingen[self._sleutel] = value
        self.async_write_ha_state()
