"""Omroep op Frontier Silicon tuners (o.a. Hama DIT2105SBTX).

Deze module heeft geen Home Assistant afhankelijkheden, enkel aiohttp,
zodat ze ook los getest kan worden.

Werking van een omroepbericht:
 1. huidige toestand bewaren (aan/uit, bron, zender, volume, mute)
 2. volume naar het omroepvolume, bericht via DLNA (AVTransport) afspelen
 3. herstel: gemute langs een stille bron (AUX in) terug naar de originele
    bron, wachten tot de zender weer speelt, zo nodig de favoriet kiezen,
    volume terugzetten en controleren, mute eraf.

Vastgestelde eigenaardigheden van de firmware (V4.5.13):
 * de DLNA renderer publiceert zijn diensten niet in dd.xml, maar
   /AVTransport/control op poort 8080 werkt wel;
 * na DLNA start DAB niet opnieuw als je rechtstreeks naar DAB schakelt,
   wel na een omweg via een andere bron;
 * bij het opstarten van DAB zet de tuner zijn eigen volume terug,
   daarom wordt het volume pas daarna hersteld.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from html import escape
from typing import Any
from urllib.parse import quote

import aiohttp

_LOGGER = logging.getLogger(__name__)

AVT = "urn:schemas-upnp-org:service:AVTransport:1"
PLAYING = "2"
STILLE_BRON_IDS = ("AUXIN", "AUX", "AUXIN1")
RADIO_BRON_IDS = ("DAB", "FM", "IR", "AIRABLE_RADIO")


class TunerFout(Exception):
    """Fout in de communicatie met de tuner."""


@dataclass
class Toestand:
    """Bewaarde toestand van de tuner voor het bericht."""

    power: str
    mode: str
    volume: str
    mute: str
    zender: str


@dataclass
class Resultaat:
    """Uitkomst van een omroepbericht."""

    gespeeld: int = 0
    gevraagd: int = 0
    hersteld: bool = False
    zender_vanzelf: bool | None = None
    fouten: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.gespeeld == self.gevraagd and self.hersteld and not self.fouten


class FrontierOmroep:
    """Stuurt een Frontier Silicon tuner aan via FSAPI en DLNA."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        pin: str = "1234",
        fsapi_port: int = 80,
        dmr_port: int = 8080,
    ) -> None:
        self._session = session
        self.host = host
        self._pin = pin
        self._fs = f"http://{host}:{fsapi_port}/fsapi"
        self._avt = f"http://{host}:{dmr_port}/AVTransport/control"
        self._modes: dict[str, str] | None = None  # id -> key

    # ------------------------------------------------------------- FSAPI
    async def _fsapi(self, op: str, node: str, value: Any = None, extra: str = "") -> str:
        url = f"{self._fs}/{op}/{node}?pin={quote(self._pin)}{extra}"
        if value is not None:
            url += f"&value={quote(str(value))}"
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                tekst = await resp.text(errors="ignore")
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise TunerFout(f"{op} {node}: {err}") from err
        status = re.search(r"<status>(\w+)</status>", tekst)
        if not status or status.group(1) != "FS_OK":
            raise TunerFout(f"{op} {node}: {status.group(1) if status else 'geen antwoord'}")
        return tekst

    async def get(self, node: str) -> str:
        tekst = await self._fsapi("GET", node)
        m = re.search(r"<value><\w+>(.*?)</\w+></value>", tekst, re.S)
        return m.group(1).strip() if m else ""

    async def set(self, node: str, value: Any) -> None:
        await self._fsapi("SET", node, value)

    async def _lijst(self, node: str) -> list[dict[str, str]]:
        tekst = await self._fsapi("LIST_GET_NEXT", f"{node}/-1", extra="&maxItems=100")
        items = []
        for key, body in re.findall(r'<item key="(\d+)">(.*?)</item>', tekst, re.S):
            velden = dict(re.findall(r'<field name="(\w+)"><\w+>(.*?)</\w+></field>', body, re.S))
            velden["key"] = key
            items.append(velden)
        return items

    async def bronnen(self) -> dict[str, str]:
        """Geef bron-id -> key (bv. DAB -> 5)."""
        if self._modes is None:
            self._modes = {m.get("id", ""): m["key"] for m in await self._lijst("netRemote.sys.caps.validModes")}
        return self._modes

    async def info(self) -> dict[str, str]:
        """Basisinfo voor de config flow."""
        return {
            "naam": await self.get("netRemote.sys.info.friendlyName"),
            "versie": await self.get("netRemote.sys.info.version"),
        }

    async def toestand(self) -> Toestand:
        return Toestand(
            power=await self.get("netRemote.sys.power"),
            mode=await self.get("netRemote.sys.mode"),
            volume=await self.get("netRemote.sys.audio.volume"),
            mute=await self.get("netRemote.sys.audio.mute"),
            zender=await self.get("netRemote.play.info.name"),
        )

    async def max_volume(self) -> int:
        stappen = await self.get("netRemote.sys.caps.volumeSteps")
        return max(int(stappen or 33) - 1, 1)

    # -------------------------------------------------------------- DLNA
    async def _soap(self, actie: str, args: dict[str, Any]) -> str:
        body = "".join(f"<{k}>{v}</{k}>" for k, v in args.items())
        env = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:{actie} xmlns:u="{AVT}">{body}</u:{actie}></s:Body></s:Envelope>'
        )
        # De renderer sluit verbindingen na een bericht: nooit keep-alive hergebruiken
        # en bij een verbroken verbinding opnieuw proberen.
        headers = {
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPACTION": f'"{AVT}#{actie}"',
            "Connection": "close",
        }
        laatste: Exception | None = None
        for poging in range(3):
            try:
                async with self._session.post(
                    self._avt, data=env.encode(), headers=headers, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    tekst = await resp.text(errors="ignore")
                    if resp.status != 200:
                        raise TunerFout(f"DLNA {actie}: HTTP {resp.status}")
                    return tekst
            except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError) as err:
                laatste = err
                await asyncio.sleep(1 + poging)
        raise TunerFout(f"DLNA {actie}: {laatste}")

    async def transport_status(self) -> str:
        tekst = await self._soap("GetTransportInfo", {"InstanceID": 0})
        m = re.search(r"<CurrentTransportState>(.*?)<", tekst)
        return m.group(1) if m else ""

    async def speel_url(self, url: str, max_duur: float = 600) -> bool:
        """Speel een bestand af en wacht tot het gedaan is."""
        await self._soap(
            "SetAVTransportURI", {"InstanceID": 0, "CurrentURI": escape(url), "CurrentURIMetaData": ""}
        )
        await self._soap("Play", {"InstanceID": 0, "Speed": 1})
        start = time.monotonic()
        speelde = False
        while time.monotonic() - start < max_duur:
            await asyncio.sleep(0.25)
            status = await self.transport_status()
            if status in ("PLAYING", "TRANSITIONING"):
                speelde = True
            elif speelde and status in ("STOPPED", "NO_MEDIA_PRESENT"):
                await asyncio.sleep(1)  # renderer even laten afronden voor een volgende opdracht
                return True
            elif not speelde and time.monotonic() - start > 20:
                raise TunerFout(f"bericht start niet (status {status})")
        raise TunerFout("bericht duurt langer dan de maximale duur")

    # ----------------------------------------------------------- herstel
    async def _kies_favoriet(self, naam: str) -> bool:
        await self.set("netRemote.nav.state", 1)
        await asyncio.sleep(1)
        for item in await self._lijst("netRemote.nav.presets"):
            if item.get("name", "").strip() and item["name"].strip() == naam.strip():
                await self.set("netRemote.nav.action.selectPreset", item["key"])
                return True
        return False

    async def _wacht_op_zender(self, naam: str, seconden: float) -> bool:
        einde = time.monotonic() + seconden
        while time.monotonic() < einde:
            await asyncio.sleep(0.5)
            try:
                if await self.get("netRemote.play.status") == PLAYING and (
                    not naam.strip() or (await self.get("netRemote.play.info.name")).strip() == naam.strip()
                ):
                    return True
            except TunerFout:
                continue
        return False

    async def herstel(self, oud: Toestand, resultaat: Resultaat) -> None:
        bronnen = await self.bronnen()
        key_naar_id = {v: k for k, v in bronnen.items()}
        stil = next((bronnen[i] for i in STILLE_BRON_IDS if i in bronnen), None)

        await self.set("netRemote.sys.audio.mute", 1)
        if stil is not None and stil != oud.mode:
            await self.set("netRemote.sys.mode", stil)
            await asyncio.sleep(1.5)
        await self.set("netRemote.sys.mode", oud.mode)

        if oud.power == "1" and key_naar_id.get(oud.mode) in RADIO_BRON_IDS and oud.zender.strip():
            resultaat.zender_vanzelf = await self._wacht_op_zender(oud.zender, 8)
            if not resultaat.zender_vanzelf:
                if await self._kies_favoriet(oud.zender):
                    await self._wacht_op_zender(oud.zender, 8)
                else:
                    resultaat.fouten.append(f"zender '{oud.zender.strip()}' niet in favorieten")
        else:
            await asyncio.sleep(2)

        # volume pas nu terugzetten: de tuner overschrijft het bij het opstarten van de bron
        for _ in range(6):
            await self.set("netRemote.sys.audio.volume", oud.volume)
            await asyncio.sleep(0.5)
            if await self.get("netRemote.sys.audio.volume") == oud.volume:
                break
        else:
            resultaat.fouten.append("volume niet correct hersteld")

        await self.set("netRemote.sys.audio.mute", oud.mute or 0)
        if oud.power == "0":
            await self.set("netRemote.sys.power", 0)
        resultaat.hersteld = True

    # ------------------------------------------------------------ omroep
    async def omroep(
        self, url: str, volume: int | None = None, herhalingen: int = 1, pauze: float = 1.0
    ) -> Resultaat:
        """Speel een bericht af en herstel daarna de vorige toestand."""
        resultaat = Resultaat(gevraagd=max(1, int(herhalingen)))
        oud = await self.toestand()
        _LOGGER.debug("Toestand voor bericht: %s", oud)
        try:
            if oud.power != "1":
                await self.set("netRemote.sys.power", 1)
                await asyncio.sleep(2)
            if volume is not None:
                vmax = await self.max_volume()
                await self.set("netRemote.sys.audio.volume", max(0, min(int(volume), vmax)))
            await self.set("netRemote.sys.audio.mute", 0)
            for keer in range(resultaat.gevraagd):
                if await self.speel_url(url):
                    resultaat.gespeeld += 1
                if keer < resultaat.gevraagd - 1 and pauze > 0:
                    await asyncio.sleep(pauze)
        except TunerFout as err:
            resultaat.fouten.append(str(err))
            _LOGGER.warning("Omroep onderbroken: %s", err)
        finally:
            # herstel altijd, ook na een fout, zodat het nooit stil blijft
            for poging in range(3):
                try:
                    await self.herstel(oud, resultaat)
                    break
                except TunerFout as err:
                    _LOGGER.warning("Herstel poging %s mislukt: %s", poging + 1, err)
                    await asyncio.sleep(2)
            else:
                resultaat.fouten.append("herstel mislukt")
        return resultaat
