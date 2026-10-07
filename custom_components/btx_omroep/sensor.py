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

STATUSSEN = ["klaar", "bezig", "fout"]


async def async_setup_entry(
    hass: HomeAssistant, entry: OmroepConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([OmroepStatus(entry)])


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
