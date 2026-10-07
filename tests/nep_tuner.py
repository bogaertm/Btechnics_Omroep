"""Nagebootste Frontier tuner (FSAPI + DLNA) met de eigenaardigheden van de echte firmware."""

from __future__ import annotations

import asyncio
import re

from aiohttp import web

MODES = ["AIRABLE_RADIO", "AIRABLE_PODCASTS", "AIRABLE_AMAZON_MP", "Spotify", "MP", "DAB", "FM", "Bluetooth", "AUXIN"]
PRESETS = ["VRT StuBru", "VRT MNM", "Qmusic"]


class NepTuner:
    def __init__(self) -> None:
        self.power = 1
        self.mode = 5
        self.volume = 25
        self.mute = 0
        self.zender = "VRT StuBru"
        self.status = 2  # speelt
        self.vorige_mode_was_dmr = False
        self.transport = "STOPPED"
        self.gespeeld: list[str] = []
        self.volume_tijdens_bericht: list[int] = []
        self.dab_volume_bij_start = 27  # firmware zet bij DAB start een eigen volume
        self.duur = 1.5
        self._taak: asyncio.Task | None = None
        self.app = web.Application()
        self.app.router.add_get("/fsapi/{op}/{pad:.*}", self.fsapi)
        self.app.router.add_post("/AVTransport/control", self.avt)

    def _ok(self, inhoud: str = "") -> web.Response:
        return web.Response(text=f"<fsapiResponse><status>FS_OK</status>{inhoud}</fsapiResponse>")

    async def fsapi(self, req: web.Request) -> web.Response:
        if req.query.get("pin") != "1234":
            return web.Response(status=403, text="<fsapiResponse><status>FS_FAIL</status></fsapiResponse>")
        op, pad = req.match_info["op"], req.match_info["pad"]
        waarde = req.query.get("value")
        if op == "LIST_GET_NEXT":
            if pad.startswith("netRemote.sys.caps.validModes"):
                items = "".join(
                    f'<item key="{i}"><field name="id"><c8_array>{m}</c8_array></field></item>' for i, m in enumerate(MODES)
                )
            else:
                items = "".join(
                    f'<item key="{i}"><field name="name"><c8_array>{n}      </c8_array></field></item>'
                    for i, n in enumerate(PRESETS)
                )
            return self._ok(items)
        if op == "GET":
            waarden = {
                "netRemote.sys.power": ("u8", self.power),
                "netRemote.sys.mode": ("u32", self.mode),
                "netRemote.sys.audio.volume": ("u8", self.volume),
                "netRemote.sys.audio.mute": ("u8", self.mute),
                "netRemote.play.info.name": ("c8_array", self.zender + "      " if self.zender else ""),
                "netRemote.play.status": ("u8", self.status),
                "netRemote.sys.caps.volumeSteps": ("u8", 33),
                "netRemote.sys.info.friendlyName": ("c8_array", "Nep tuner"),
                "netRemote.sys.info.version": ("c8_array", "test"),
            }
            t, v = waarden[pad]
            return self._ok(f"<value><{t}>{v}</{t}></value>")
        # SET
        if pad == "netRemote.sys.mode":
            nieuw = int(waarde)
            if MODES[nieuw] == "DAB":
                if self.vorige_mode_was_dmr:
                    self.status, self.zender = 0, ""  # DAB blijft stil na DLNA
                else:
                    self.status, self.zender = 2, "VRT StuBru"
                    self.volume = self.dab_volume_bij_start
            else:
                self.status, self.zender = 0, ""
            self.vorige_mode_was_dmr = MODES[nieuw] == "MP"
            self.mode = nieuw
        elif pad == "netRemote.sys.audio.volume":
            self.volume = int(waarde)
        elif pad == "netRemote.sys.audio.mute":
            self.mute = int(waarde)
        elif pad == "netRemote.sys.power":
            self.power = int(waarde)
        elif pad == "netRemote.nav.action.selectPreset":
            self.zender, self.status = PRESETS[int(waarde)], 2
            self.volume = self.dab_volume_bij_start
        return self._ok()

    async def avt(self, req: web.Request) -> web.Response:
        body = await req.text()
        actie = re.search(r"<u:(\w+)", body).group(1)
        if actie == "SetAVTransportURI":
            self.gespeeld.append(re.search(r"<CurrentURI>(.*?)</CurrentURI>", body).group(1))
            self.mode, self.vorige_mode_was_dmr, self.status = 4, True, 0
        elif actie == "Play":
            self.volume_tijdens_bericht.append(self.volume)
            self.transport = "PLAYING"

            async def klaar() -> None:
                await asyncio.sleep(self.duur)
                self.transport = "STOPPED"

            self._taak = asyncio.create_task(klaar())
        inhoud = f"<CurrentTransportState>{self.transport}</CurrentTransportState>" if actie == "GetTransportInfo" else ""
        return web.Response(text=f"<s:Envelope><s:Body>{inhoud}</s:Body></s:Envelope>")
