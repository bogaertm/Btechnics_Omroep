"""Periodiek uitlezen van de tuner voor de entiteiten (aan/uit, zender, volume)."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .tuner import FrontierOmroep, TunerFout

_LOGGER = logging.getLogger(__name__)

FAVORIETEN_VERNIEUWEN = 600  # seconden


class OmroepCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Leest de tuner elke 30 s, behalve tijdens een omroepbericht."""

    def __init__(self, hass: HomeAssistant, tuner: FrontierOmroep, lock: asyncio.Lock) -> None:
        super().__init__(hass, _LOGGER, name=f"{DOMAIN} {tuner.host}", update_interval=timedelta(seconds=30))
        self.tuner = tuner
        self.lock = lock
        self.favorieten: list[dict[str, str]] = []
        self._favorieten_tijd = 0.0

    async def _async_update_data(self) -> dict[str, Any]:
        if self.lock.locked() and self.data is not None:
            # tijdens een bericht staat de tuner tijdelijk op DLNA: vorige toestand blijven tonen
            return self.data
        try:
            data = await self.tuner.momentopname()
            dab = await self.tuner.dab_key()
            data["is_dab"] = data["power"] and data["mode"] == dab
            if data["is_dab"] and (
                not self.favorieten or time.monotonic() - self._favorieten_tijd > FAVORIETEN_VERNIEUWEN
            ):
                self.favorieten = await self.tuner.dab_favorieten()
                self._favorieten_tijd = time.monotonic()
            data["max_volume"] = await self.tuner.max_volume()
        except TunerFout as err:
            raise UpdateFailed(f"Tuner niet bereikbaar: {err}") from err
        return data

    def favoriet_label(self, fav: dict[str, str]) -> str:
        """Uniek label: dezelfde zender kan meerdere keren in de favorieten staan."""
        return f"{int(fav['key']) + 1}. {fav['naam']}"
