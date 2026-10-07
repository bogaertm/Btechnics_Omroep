"""Tekstvelden: omroeptekst en naam om een tekst als boodschap op te slaan."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import OmroepConfigEntry, bewaar_en_meld
from .const import DOMAIN
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
        # naamveld leegmaken na opslaan zichtbaar maken
        @callback
        def _ververs(_event) -> None:
            self.async_write_ha_state()

        self.async_on_remove(self.hass.bus.async_listen(f"{DOMAIN}_boodschappen_gewijzigd", _ververs))

    @property
    def native_value(self) -> str:
        return self._entry.runtime_data.instellingen.get(self._sleutel) or ""

    async def async_set_value(self, value: str) -> None:
        inst = self._entry.runtime_data.instellingen
        inst[self._sleutel] = value
        self.async_write_ha_state()
        # naam bevestigd (Gereed/Return) terwijl er een tekst klaarstaat: meteen opslaan,
        # zodat op een iPhone of iPad geen tweede tik op de knop nodig is
        if self._sleutel == "naam" and value.strip() and (inst.get("tekst") or "").strip():
            await bewaar_en_meld(self.hass, self._entry)
            self.async_write_ha_state()
