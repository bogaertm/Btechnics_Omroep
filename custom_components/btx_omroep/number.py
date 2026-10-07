"""Volume van de radio."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import OmroepConfigEntry
from .entiteit import OmroepEntiteit


async def async_setup_entry(
    hass: HomeAssistant, entry: OmroepConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c = entry.runtime_data.coordinator
    async_add_entities(
        [
            RadioVolume(c, entry, "volume"),
            OmroepInstelling(c, entry, "omroep_volume", "volume", 0, 32, "mdi:bullhorn-variant"),
            OmroepInstelling(c, entry, "herhalingen", "herhalingen", 1, 5, "mdi:repeat"),
        ]
    )


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


class OmroepInstelling(OmroepEntiteit, NumberEntity, RestoreEntity):
    """Volume en aantal keer voor de dashboardknoppen."""

    _attr_mode = NumberMode.SLIDER
    _attr_native_step = 1

    def __init__(self, coordinator, entry: OmroepConfigEntry, sleutel: str, veld: str, laag: int, hoog: int, icoon: str) -> None:
        super().__init__(coordinator, entry, sleutel)
        self._entry = entry
        self._veld = veld
        self._attr_native_min_value = laag
        self._attr_native_max_value = hoog
        self._attr_icon = icoon

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        vorig = await self.async_get_last_state()
        if vorig is not None:
            try:
                self._entry.runtime_data.instellingen[self._veld] = int(float(vorig.state))
            except ValueError:
                pass

    @property
    def native_value(self) -> float:
        return self._entry.runtime_data.instellingen[self._veld]

    async def async_set_native_value(self, value: float) -> None:
        self._entry.runtime_data.instellingen[self._veld] = int(value)
        self.async_write_ha_state()
