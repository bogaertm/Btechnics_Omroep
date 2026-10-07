"""DAB zender kiezen uit de favorieten van de tuner."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.restore_state import RestoreEntity

from . import OmroepConfigEntry, boodschappen
from .const import DOMAIN
from .entiteit import OmroepEntiteit
from .tuner import TunerFout


async def async_setup_entry(
    hass: HomeAssistant, entry: OmroepConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c = entry.runtime_data.coordinator
    async_add_entities([DabZender(c, entry, "zender"), Boodschap(c, entry, "boodschap")])


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


class Boodschap(OmroepEntiteit, SelectEntity, RestoreEntity):
    """Keuzelijst met de geluidsbestanden in <mediamap>/omroep."""

    _attr_icon = "mdi:playlist-music"

    def __init__(self, coordinator, entry: OmroepConfigEntry, sleutel: str) -> None:
        super().__init__(coordinator, entry, sleutel)
        self._entry = entry
        self._attr_options: list[str] = []

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (vorig := await self.async_get_last_state()) is not None and vorig.state not in ("unknown", "unavailable"):
            self._entry.runtime_data.instellingen["boodschap"] = vorig.state
        await self._lees_map()
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_boodschappen_gewijzigd", self._gewijzigd)
        )
        # nieuwe uploads oppikken
        self.async_on_remove(async_track_time_interval(self.hass, self._periodiek, timedelta(seconds=30)))

    async def _lees_map(self) -> None:
        self._attr_options = await self.hass.async_add_executor_job(boodschappen, self.hass)

    async def _periodiek(self, _now) -> None:
        oud = self._attr_options
        await self._lees_map()
        if oud != self._attr_options:
            self.async_write_ha_state()

    async def _gewijzigd(self, _event) -> None:
        await self._lees_map()
        self.async_write_ha_state()

    @property
    def options(self) -> list[str]:
        return self._attr_options

    @property
    def current_option(self) -> str | None:
        keuze = self._entry.runtime_data.instellingen.get("boodschap")
        return keuze if keuze in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        self._entry.runtime_data.instellingen["boodschap"] = option
        self.async_write_ha_state()
