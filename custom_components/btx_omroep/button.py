"""Knoppen: gekozen boodschap afspelen, tekst omroepen, tekst opslaan als boodschap."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import OmroepConfigEntry, bewaar_tekst_als_boodschap
from .const import DOMAIN, MAP_OMROEP, SERVICE_OMROEP
from .entiteit import OmroepEntiteit


async def async_setup_entry(
    hass: HomeAssistant, entry: OmroepConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c = entry.runtime_data.coordinator
    async_add_entities(
        [
            BoodschapAfspelen(c, entry, "boodschap_afspelen"),
            TekstOmroepen(c, entry, "tekst_omroepen"),
            TekstOpslaan(c, entry, "tekst_opslaan"),
        ]
    )


class _OmroepKnop(OmroepEntiteit, ButtonEntity):
    def __init__(self, coordinator, entry: OmroepConfigEntry, sleutel: str) -> None:
        super().__init__(coordinator, entry, sleutel)
        self._entry = entry

    @property
    def _inst(self) -> dict:
        return self._entry.runtime_data.instellingen

    async def _omroep(self, **data) -> None:
        await self.hass.services.async_call(
            DOMAIN,
            SERVICE_OMROEP,
            {
                "tuner": self._entry.entry_id,
                "volume": int(self._inst["volume"]),
                "herhalingen": int(self._inst["herhalingen"]),
                "pauze": 2,
                **data,
            },
            blocking=True,
        )


class BoodschapAfspelen(_OmroepKnop):
    _attr_icon = "mdi:play-circle"

    async def async_press(self) -> None:
        naam = self._inst.get("boodschap")
        if not naam:
            raise ServiceValidationError("Kies eerst een boodschap")
        await self._omroep(bericht=f"{MAP_OMROEP}/{naam}")


class TekstOmroepen(_OmroepKnop):
    _attr_icon = "mdi:account-voice"

    async def async_press(self) -> None:
        tekst = (self._inst.get("tekst") or "").strip()
        if not tekst:
            raise ServiceValidationError("Vul eerst een tekst in")
        await self._omroep(tekst=tekst)


class TekstOpslaan(_OmroepKnop):
    _attr_icon = "mdi:content-save"

    async def async_press(self) -> None:
        naam = await bewaar_tekst_als_boodschap(
            self.hass, self._entry, self._inst.get("tekst") or "", self._inst.get("naam") or ""
        )
        # meteen selecteren, zodat hij klaar staat om af te spelen of in te plannen
        self._inst["boodschap"] = naam
        self.hass.bus.async_fire(f"{DOMAIN}_boodschappen_gewijzigd", {"naam": naam})
