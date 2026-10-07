"""Btechnics Omroep: omroepberichten op Frontier Silicon tuners met herstel van de radio."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

import voluptuous as vol
from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.components.network import async_get_source_ip
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_BERICHT,
    ATTR_HERHALINGEN,
    ATTR_PAUZE,
    ATTR_TUNER,
    ATTR_VOLUME,
    CONF_BASIS_URL,
    CONF_PIN,
    DEFAULT_PIN,
    DOMAIN,
    SERVICE_OMROEP,
    SIGNAAL_STATUS,
    URL_BESTAND,
)
from .tuner import FrontierOmroep, TunerFout

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

OMROEP_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_TUNER): vol.Any(None, cv.string),
        vol.Required(ATTR_BERICHT): vol.Any(cv.string, dict),
        vol.Optional(ATTR_VOLUME): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Optional(ATTR_HERHALINGEN, default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
        vol.Optional(ATTR_PAUZE, default=1): vol.All(vol.Coerce(float), vol.Range(min=0, max=300)),
    }
)


@dataclass
class OmroepData:
    """Runtime data per tuner."""

    tuner: FrontierOmroep
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    status: str = "klaar"
    attributen: dict[str, Any] = field(default_factory=dict)


type OmroepConfigEntry = ConfigEntry[OmroepData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Webview voor de bestanden en de actie registreren (één keer)."""
    hass.data.setdefault(DOMAIN, {"bestanden": {}})
    hass.http.register_view(BestandView(hass))

    async def _omroep(call: ServiceCall) -> ServiceResponse:
        return await _voer_omroep_uit(hass, call)

    hass.services.async_register(
        DOMAIN, SERVICE_OMROEP, _omroep, schema=OMROEP_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: OmroepConfigEntry) -> bool:
    tuner = FrontierOmroep(
        async_get_clientsession(hass), entry.data[CONF_HOST], entry.options.get(CONF_PIN, entry.data.get(CONF_PIN, DEFAULT_PIN))
    )
    try:
        await tuner.bronnen()
    except TunerFout as err:
        raise ConfigEntryNotReady(f"Tuner {entry.data[CONF_HOST]} niet bereikbaar: {err}") from err
    entry.runtime_data = OmroepData(tuner=tuner)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_opties_gewijzigd))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OmroepConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _opties_gewijzigd(hass: HomeAssistant, entry: OmroepConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


# ---------------------------------------------------------------- helpers
def _kies_entry(hass: HomeAssistant, entry_id: str | None) -> OmroepConfigEntry:
    entries = [e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED]
    if entry_id:
        entries = [e for e in entries if e.entry_id == entry_id]
    if not entries:
        raise ServiceValidationError("Geen (geladen) tuner gevonden voor Btechnics Omroep")
    if len(entries) > 1:
        raise ServiceValidationError("Meerdere tuners ingesteld: kies er één via 'tuner'")
    return entries[0]


def _media_mappen(hass: HomeAssistant) -> dict[str, Path]:
    return {k: Path(v).resolve() for k, v in hass.config.media_dirs.items()}


def _bestand_pad(hass: HomeAssistant, bericht: Any) -> Path:
    """Zet een media-source id of pad om naar een bestand binnen de mediamappen."""
    if isinstance(bericht, dict):
        bericht = bericht.get("media_content_id", "")
    bericht = str(bericht).strip()
    mappen = _media_mappen(hass)
    if not mappen:
        raise ServiceValidationError("Geen mediamap ingesteld in Home Assistant")

    m = re.match(r"^media-source://media_source/([^/]+)/(.+)$", bericht)
    if m:
        basis = mappen.get(m.group(1))
        if basis is None:
            raise ServiceValidationError(f"Onbekende mediamap '{m.group(1)}'")
        pad = (basis / unquote(m.group(2))).resolve()
    elif bericht.startswith("media-source://"):
        raise ServiceValidationError("Enkel lokale media (media_source) wordt ondersteund")
    elif os.path.isabs(bericht):
        pad = Path(bericht).resolve()
    else:
        basis = mappen.get("local", next(iter(mappen.values())))
        pad = (basis / bericht).resolve()

    if not any(pad.is_relative_to(map_) for map_ in mappen.values()):
        raise ServiceValidationError("Bestand ligt buiten de mediamappen van Home Assistant")
    if not pad.is_file():
        raise ServiceValidationError(f"Bestand niet gevonden: {pad}")
    return pad


async def _basis_url(hass: HomeAssistant, entry: OmroepConfigEntry) -> str:
    """URL waarop de tuner Home Assistant kan bereiken (bij voorkeur een IP adres)."""
    if url := entry.options.get(CONF_BASIS_URL):
        return url.rstrip("/")
    ip = await async_get_source_ip(hass)
    schema = "https" if hass.config.api and hass.config.api.use_ssl else "http"
    poort = hass.http.server_port or 8123
    return f"{schema}://{ip}:{poort}"


def _zet_status(hass: HomeAssistant, entry: OmroepConfigEntry, status: str, **attributen: Any) -> None:
    data = entry.runtime_data
    data.status = status
    data.attributen.update(attributen)
    async_dispatcher_send(hass, SIGNAAL_STATUS.format(entry.entry_id))


async def _voer_omroep_uit(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    entry = _kies_entry(hass, call.data.get(ATTR_TUNER))
    data = entry.runtime_data
    pad = await hass.async_add_executor_job(_bestand_pad, hass, call.data[ATTR_BERICHT])
    token = secrets.token_urlsafe(16)
    url = await _basis_url(hass, entry) + URL_BESTAND.format(token=token, naam=quote(pad.name))
    bestanden: dict[str, Path] = hass.data[DOMAIN]["bestanden"]

    # één bericht tegelijk per tuner: volgende berichten wachten in de rij
    async with data.lock:
        _zet_status(hass, entry, "bezig", bericht=pad.name, gestart=dt_util.now().isoformat())
        bestanden[token] = pad
        try:
            resultaat = await data.tuner.omroep(
                url,
                volume=call.data.get(ATTR_VOLUME),
                herhalingen=call.data[ATTR_HERHALINGEN],
                pauze=call.data[ATTR_PAUZE],
            )
        except TunerFout as err:
            _zet_status(hass, entry, "fout", fouten=[str(err)])
            raise HomeAssistantError(f"Omroep mislukt: {err}") from err
        finally:
            bestanden.pop(token, None)

        _zet_status(
            hass,
            entry,
            "klaar" if resultaat.ok else "fout",
            gespeeld=resultaat.gespeeld,
            gevraagd=resultaat.gevraagd,
            hersteld=resultaat.hersteld,
            fouten=resultaat.fouten,
            beeindigd=dt_util.now().isoformat(),
        )

    if not resultaat.ok:
        _LOGGER.warning("Omroep %s niet volledig gelukt: %s", pad.name, resultaat.fouten)
    if call.return_response:
        return {
            "bericht": pad.name,
            "gespeeld": resultaat.gespeeld,
            "gevraagd": resultaat.gevraagd,
            "hersteld": resultaat.hersteld,
            "zender_vanzelf": resultaat.zender_vanzelf,
            "fouten": resultaat.fouten,
        }
    return None


class BestandView(HomeAssistantView):
    """Bied het bericht aan de tuner aan via een eenmalige, geheime link."""

    url = URL_BESTAND
    name = "api:btx_omroep:bestand"
    requires_auth = False  # de tuner kan niet inloggen; de link is geheim en enkel geldig tijdens het bericht

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    def _pad(self, token: str) -> Path:
        pad = self.hass.data.get(DOMAIN, {}).get("bestanden", {}).get(token)
        if pad is None:
            raise web.HTTPNotFound
        return pad

    async def get(self, request: web.Request, token: str, naam: str) -> web.FileResponse:
        return web.FileResponse(self._pad(token))

    async def head(self, request: web.Request, token: str, naam: str) -> web.FileResponse:
        return web.FileResponse(self._pad(token))
