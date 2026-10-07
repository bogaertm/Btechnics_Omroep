"""DAB zender kiezen uit de favorieten van de tuner."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import OmroepConfigEntry
from .entiteit import OmroepEntiteit
from .tuner import TunerFout


async def async_setup_entry(
    hass: HomeAssistant, entry: OmroepConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([DabZender(entry.runtime_data.coordinator, entry, "zender")])


class DabZender(OmroepEntiteit, SelectEntity):
    _attr_icon = "mdi:radio-tower"

    @property
    def options(self) -> list[str]:
        return [self.coordinator.favoriet_label(f) for f in self.coordinator.favorieten]

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data or {}
        if not data.get("is_dab"):
            return None
        naam = data.get("zender", "")
        # eerste favoriet met dezelfde naam (een zender kan dubbel in de favorieten staan)
        for fav in self.coordinator.favorieten:
            if fav["naam"] == naam:
                return self.coordinator.favoriet_label(fav)
        return None

    async def async_select_option(self, option: str) -> None:
        fav = next((f for f in self.coordinator.favorieten if self.coordinator.favoriet_label(f) == option), None)
        if fav is None:
            raise HomeAssistantError(f"Onbekende zender {option}")
        async with self.coordinator.lock:
            try:
                await self.coordinator.tuner.kies_dab_favoriet(fav["key"])
            except TunerFout as err:
                raise HomeAssistantError(f"Zender kiezen mislukt: {err}") from err
        await self._na_actie()
