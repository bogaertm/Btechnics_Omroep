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

import aiohttp
import voluptuous as vol
from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.components.network import async_get_source_ip
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_BERICHT,
    ATTR_HERHALINGEN,
    ATTR_MUZIEKJE,
    ATTR_PAUZE,
    ATTR_TEKST,
    ATTR_TUNER,
    ATTR_VOLUME,
    AUDIO_EXTENSIES,
    CONF_BASIS_URL,
    CONF_PIN,
    CONF_TTS,
    GELUID_IN,
    GELUID_UIT,
    MAP_OMROEP,
    DEFAULT_PIN,
    DOMAIN,
    SERVICE_OMROEP,
    SIGNAAL_STATUS,
    URL_BESTAND,
)
from .coordinator import OmroepCoordinator
from .tuner import FrontierOmroep, Resultaat, Toestand, TunerFout

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BUTTON, Platform.NUMBER, Platform.SELECT, Platform.SENSOR, Platform.SWITCH, Platform.TEXT]
GELUID_MAP = Path(__file__).parent / "geluid"
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

OMROEP_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_TUNER): vol.Any(None, cv.string),
        vol.Optional(ATTR_BERICHT): vol.Any(cv.string, dict),
        vol.Optional(ATTR_TEKST): cv.string,
        vol.Optional(ATTR_MUZIEKJE): cv.boolean,
        vol.Optional(ATTR_VOLUME): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Optional(ATTR_HERHALINGEN, default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
        vol.Optional(ATTR_PAUZE, default=1): vol.All(vol.Coerce(float), vol.Range(min=0, max=300)),
    }
)


@dataclass
class OmroepData:
    """Runtime data per tuner."""

    tuner: FrontierOmroep
    sessie: aiohttp.ClientSession
    lock: asyncio.Lock
    coordinator: OmroepCoordinator
    status: str = "klaar"
    attributen: dict[str, Any] = field(default_factory=dict)
    # instellingen van de dashboardknoppen (bewaard door de entiteiten zelf)
    instellingen: dict[str, Any] = field(
        default_factory=lambda: {"muziekje": True, "volume": 32, "herhalingen": 1, "tekst": "", "naam": "", "boodschap": None}
    )


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
    host = entry.data[CONF_HOST]
    # eigen sessie zonder keep-alive: de DLNA renderer sluit verbindingen na een bericht
    sessie = aiohttp.ClientSession(connector=aiohttp.TCPConnector(force_close=True))
    tuner = FrontierOmroep(sessie, host, entry.options.get(CONF_PIN, entry.data.get(CONF_PIN, DEFAULT_PIN)))
    try:
        await tuner.bronnen()
    except TunerFout as err:
        await sessie.close()
        raise ConfigEntryNotReady(f"Tuner {host} niet bereikbaar: {err}") from err
    # één wachtrij per tuner, die ook een herlaad van de integratie overleeft
    lock = hass.data[DOMAIN].setdefault("locks", {}).setdefault(host, asyncio.Lock())
    coordinator = OmroepCoordinator(hass, tuner, lock)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        await sessie.close()
        raise
    entry.runtime_data = OmroepData(tuner=tuner, sessie=sessie, lock=lock, coordinator=coordinator)
    await hass.async_add_executor_job(_maak_omroepmap, hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_opties_gewijzigd))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OmroepConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.sessie.close()
    return ok


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


def omroepmap(hass: HomeAssistant) -> Path | None:
    """Map met de boodschappen: <lokale mediamap>/omroep."""
    mappen = hass.config.media_dirs
    basis = mappen.get("local") or next(iter(mappen.values()), None)
    return Path(basis) / MAP_OMROEP if basis else None


def _maak_omroepmap(hass: HomeAssistant) -> None:
    if (map_ := omroepmap(hass)) is not None:
        try:
            map_.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            _LOGGER.warning("Kon map %s niet aanmaken: %s", map_, err)


def boodschappen(hass: HomeAssistant) -> list[str]:
    """Bestandsnamen van de boodschappen in de omroepmap (voor de keuzelijst)."""
    map_ = omroepmap(hass)
    if map_ is None or not map_.is_dir():
        return []
    return sorted(
        (p.name for p in map_.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIES),
        key=str.lower,
    )


def _standaard_tts(hass: HomeAssistant) -> str | None:
    """Kies een stem: eerst in de taal van Home Assistant, bij voorkeur Google Translate."""
    tts = sorted(hass.states.async_entity_ids("tts"))
    taal = (hass.config.language or "nl").split("-")[0].lower()

    def score(eid: str) -> tuple[int, int]:
        delen = eid.split(".", 1)[1].split("_")
        return (0 if taal in delen else 1, 0 if "google_translate" in eid else 1)

    return min(tts, key=score) if tts else None


async def _tts_url(hass: HomeAssistant, entry: OmroepConfigEntry, tekst: str, basis: str) -> str:
    """Laat Home Assistant de tekst omzetten naar spraak en geef de link voor de tuner."""
    from homeassistant.components import media_source, tts  # noqa: PLC0415

    engine = entry.options.get(CONF_TTS) or _standaard_tts(hass)
    if not engine:
        raise ServiceValidationError(
            "Geen tekst-naar-spraak dienst gevonden: voeg bv. de integratie Google Translate text-to-speech toe"
        )
    try:
        media_id = tts.generate_media_source_id(hass, tekst, engine=engine, cache=True)
        media = await media_source.async_resolve_media(hass, media_id, None)
    except HomeAssistantError as err:
        raise HomeAssistantError(f"Tekst naar spraak mislukt: {err}") from err
    return media.url if media.url.startswith("http") else basis + media.url


def veilige_naam(naam: str) -> str:
    """Bestandsnaam zonder vreemde tekens, bv. 'Pauze 10u!' -> 'Pauze 10u'."""
    schoon = re.sub(r"[^\w \-.]", "", naam, flags=re.UNICODE).strip().strip(".")
    return re.sub(r"\s+", " ", schoon)[:60]


async def bewaar_tekst_als_boodschap(hass: HomeAssistant, entry: OmroepConfigEntry, tekst: str, naam: str) -> str:
    """Zet tekst om naar spraak en bewaar ze als bestand in de omroepmap. Geeft de bestandsnaam."""
    from homeassistant.components import tts  # noqa: PLC0415

    tekst, naam = tekst.strip(), veilige_naam(naam or tekst[:40])
    if not tekst:
        raise ServiceValidationError("Vul eerst een tekst in")
    if not naam:
        raise ServiceValidationError("Geef de boodschap een naam")
    map_ = omroepmap(hass)
    if map_ is None:
        raise ServiceValidationError("Geen mediamap ingesteld in Home Assistant")
    engine = entry.options.get(CONF_TTS) or _standaard_tts(hass)
    if not engine:
        raise ServiceValidationError("Geen tekst-naar-spraak dienst gevonden")
    media_id = tts.generate_media_source_id(hass, tekst, engine=engine, cache=True)
    try:
        extensie, inhoud = await tts.async_get_media_source_audio(hass, media_id)
    except HomeAssistantError as err:
        raise HomeAssistantError(f"Tekst naar spraak mislukt: {err}") from err
    bestand = map_ / f"{naam}.{extensie or 'mp3'}"

    def _schrijf() -> None:
        map_.mkdir(parents=True, exist_ok=True)
        bestand.write_bytes(inhoud)

    await hass.async_add_executor_job(_schrijf)
    _LOGGER.info("Boodschap %s opgeslagen", bestand)
    return bestand.name


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
        pad = (basis / m.group(2)).resolve()
        if not pad.is_file():  # sommige bronnen geven een URL gecodeerde id door
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
    # netwerkkaart kiezen die naar de tuner wijst (belangrijk bij meerdere netwerken)
    ip = await async_get_source_ip(hass, target_ip=entry.data[CONF_HOST])
    if hass.config.api and hass.config.api.use_ssl:
        _LOGGER.warning(
            "Home Assistant gebruikt SSL: de tuner kan waarschijnlijk geen https. Vul in de opties "
            "van Btechnics Omroep een http basis URL in (bv. via een extra http poort of proxy)"
        )
        schema = "https"
    else:
        schema = "http"
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
    tekst = (call.data.get(ATTR_TEKST) or "").strip()
    bericht = call.data.get(ATTR_BERICHT)
    if bool(tekst) == bool(bericht):
        raise ServiceValidationError("Geef een bericht (geluidsbestand) of een tekst, niet allebei en niet geen van beide")
    basis = await _basis_url(hass, entry)
    muziekje = call.data.get(ATTR_MUZIEKJE, data.instellingen["muziekje"])

    pad: Path | None = None
    if tekst:
        naam = f"tekst: {tekst[:60]}"
        tts_url = await _tts_url(hass, entry, tekst, basis)
    else:
        pad = await hass.async_add_executor_job(_bestand_pad, hass, bericht)
        naam = pad.name

    async def _bericht() -> tuple[Resultaat, Toestand | None]:
        # één bericht tegelijk per tuner: volgende berichten wachten in de rij
        async with data.lock:
            bestanden: dict[str, Bestand] = hass.data[DOMAIN]["bestanden"]
            tokens: list[str] = []

            def _link(bestand: Path) -> tuple[str, str]:
                token = secrets.token_urlsafe(16)
                bestanden[token] = Bestand(bestand)
                tokens.append(token)
                return token, basis + URL_BESTAND.format(token=token, naam=quote(bestand.name))

            bericht_token = None
            if pad is not None:
                bericht_token, url = _link(pad)
            else:
                url = tts_url
            intro = _link(GELUID_MAP / GELUID_IN)[1] if muziekje else None
            outro = _link(GELUID_MAP / GELUID_UIT)[1] if muziekje else None

            _zet_status(hass, entry, "bezig", bericht=naam, gestart=dt_util.now().isoformat(), fouten=[])
            oud: Toestand | None = None
            resultaat = Resultaat(gevraagd=call.data[ATTR_HERHALINGEN])
            try:
                resultaat, oud = await data.tuner.omroep(
                    url,
                    volume=call.data.get(ATTR_VOLUME),
                    herhalingen=call.data[ATTR_HERHALINGEN],
                    pauze=call.data[ATTR_PAUZE],
                    intro=intro,
                    outro=outro,
                )
                if bericht_token and not bestanden[bericht_token].opgehaald:
                    resultaat.fouten.append(
                        f"de tuner haalde het bestand niet op bij {basis}: controleer de basis URL in de opties"
                    )
                    resultaat.gespeeld = 0
            except TunerFout as err:
                resultaat.fouten.append(str(err))
            except Exception as err:  # noqa: BLE001
                resultaat.fouten.append(f"onverwachte fout: {err}")
                _LOGGER.exception("Onverwachte fout tijdens omroep")
            finally:
                for token in tokens:
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
            if oud is not None and not resultaat.hersteld and not resultaat.noodherstel:
                _plan_noodherstel(hass, data, oud)
        await data.coordinator.async_request_refresh()
        return resultaat, oud

    # in een eigen taak en afgeschermd: wordt de automatisering geannuleerd (herladen,
    # bewerken), dan loopt het bericht en vooral het herstel van de radio toch verder
    taak = hass.async_create_background_task(_bericht(), f"btx_omroep {naam}")
    resultaat, _ = await asyncio.shield(taak)

    if not resultaat.ok:
        _LOGGER.warning("Omroep %s niet volledig gelukt: %s", naam, resultaat.fouten)
        if resultaat.gespeeld == 0:
            raise HomeAssistantError(f"Omroep {naam} mislukt: {'; '.join(resultaat.fouten)}")
    if call.return_response:
        return {
            "bericht": naam,
            "gespeeld": resultaat.gespeeld,
            "gevraagd": resultaat.gevraagd,
            "hersteld": resultaat.hersteld,
            "zender_vanzelf": resultaat.zender_vanzelf,
            "fouten": resultaat.fouten,
        }
    return None


def _plan_noodherstel(hass: HomeAssistant, data: OmroepData, oud: Toestand) -> None:
    """Herstel mislukt (bv. wifi even weg): na een minuut opnieuw proberen, tot 5 keer."""

    async def _probeer(poging: int) -> None:
        async with data.lock:
            if await data.tuner.noodherstel(oud):
                _LOGGER.info("Noodherstel van de tuner gelukt (poging %s)", poging)
                return
        if poging < 5:
            async_call_later(hass, 60, lambda _: hass.async_create_task(_probeer(poging + 1)))
        else:
            _LOGGER.error("Tuner kon na een omroepbericht niet hersteld worden")

    async_call_later(hass, 60, lambda _: hass.async_create_task(_probeer(1)))


@dataclass
class Bestand:
    """Bestand dat tijdelijk via een geheime link aan de tuner aangeboden wordt."""

    pad: Path
    opgehaald: bool = False


class BestandView(HomeAssistantView):
    """Bied het bericht aan de tuner aan via een eenmalige, geheime link."""

    url = URL_BESTAND
    name = "api:btx_omroep:bestand"
    requires_auth = False  # de tuner kan niet inloggen; de link is geheim en enkel geldig tijdens het bericht

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    def _bestand(self, token: str) -> Bestand:
        bestand = self.hass.data.get(DOMAIN, {}).get("bestanden", {}).get(token)
        if bestand is None:
            raise web.HTTPNotFound
        return bestand

    async def get(self, request: web.Request, token: str, naam: str) -> web.FileResponse:
        bestand = self._bestand(token)
        bestand.opgehaald = True
        return web.FileResponse(bestand.pad)

    async def head(self, request: web.Request, token: str, naam: str) -> web.FileResponse:
        return web.FileResponse(self._bestand(token).pad)
