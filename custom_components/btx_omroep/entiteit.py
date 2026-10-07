"""Gemeenschappelijke basis voor de entiteiten."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OmroepCoordinator


def apparaat_info(entry: ConfigEntry, host: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Frontier Silicon",
        model="Omroep (Btechnics)",
        configuration_url=f"http://{host}",
    )


class OmroepEntiteit(CoordinatorEntity[OmroepCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: OmroepCoordinator, entry: ConfigEntry, sleutel: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{sleutel}"
        self._attr_translation_key = sleutel
        self._attr_device_info = apparaat_info(entry, coordinator.tuner.host)

    async def _na_actie(self) -> None:
        await self.coordinator.async_refresh()
