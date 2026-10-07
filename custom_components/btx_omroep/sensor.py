"""Statussensor van de omroep."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import OmroepConfigEntry
from .const import DOMAIN, SIGNAAL_STATUS
from .entiteit import OmroepEntiteit

STATUSSEN = ["klaar", "bezig", "fout"]


async def async_setup_entry(
    hass: HomeAssistant, entry: OmroepConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([OmroepStatus(entry), SpeeltNu(entry.runtime_data.coordinator, entry, "speelt_nu")])


class OmroepStatus(SensorEntity):
    """Toont of er een bericht speelt en hoe het vorige afliep."""

    _attr_has_entity_name = True
    _attr_translation_key = "status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUSSEN
    _attr_should_poll = False
    _attr_icon = "mdi:bullhorn"

    def __init__(self, entry: OmroepConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Frontier Silicon",
            model="Omroep (Btechnics)",
            configuration_url=f"http://{entry.runtime_data.tuner.host}",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAAL_STATUS.format(self._entry.entry_id), self._update)
        )

    @callback
    def _update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        return self._entry.runtime_data.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self._entry.runtime_data.attributen)


BRON_NAMEN = {
    "DAB": "DAB",
    "FM": "FM",
    "AIRABLE_RADIO": "Internetradio",
    "MP": "Omroepbericht",
    "AUXIN": "AUX",
    "Bluetooth": "Bluetooth",
    "Spotify": "Spotify",
}


class SpeeltNu(OmroepEntiteit, SensorEntity):
    """Wat de tuner nu speelt, ook als de zender niet in de favorieten staat."""

    _attr_icon = "mdi:radio"

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data or {}
        if not data.get("power"):
            return "Uit"
        return data.get("zender") or self._bron() or "Onbekend"

    def _bron(self) -> str | None:
        data = self.coordinator.data or {}
        modes = self.coordinator.tuner._modes or {}
        bron_id = next((k for k, v in modes.items() if v == data.get("mode")), None)
        return BRON_NAMEN.get(bron_id, bron_id) if bron_id else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        return {"bron": self._bron(), "volume": data.get("volume")}
