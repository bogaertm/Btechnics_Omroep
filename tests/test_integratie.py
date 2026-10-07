"""Tests voor Btechnics Omroep tegen een nagebootste tuner (geen echte hardware)."""

from __future__ import annotations

import functools
from pathlib import Path
from unittest.mock import patch

import pytest
from aiohttp import web
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.template import Template
from homeassistant.util.yaml import load_yaml

from custom_components.btx_omroep import tuner as tuner_mod
from custom_components.btx_omroep.const import DOMAIN

from .nep_tuner import NepTuner

ROOT = Path(__file__).parents[1]


@pytest.fixture(autouse=True)
def auto_enable(enable_custom_integrations):
    yield


@pytest.fixture
async def nep(socket_enabled):
    tuner = NepTuner()
    runner = web.AppRunner(tuner.app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    tuner.poort = site._server.sockets[0].getsockname()[1]
    echte = tuner_mod.FrontierOmroep
    maker = functools.partial(echte, fsapi_port=tuner.poort, dmr_port=tuner.poort)
    with patch("custom_components.btx_omroep.FrontierOmroep", maker), patch(
        "custom_components.btx_omroep.config_flow.FrontierOmroep", maker
    ):
        yield tuner
    await runner.cleanup()


@pytest.fixture
async def ingesteld(hass: HomeAssistant, nep, tmp_path, hass_client_no_auth):
    # echte HTTP server van HA, zodat de nagebootste tuner het bestand echt ophaalt
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "http", {})
    client = await hass_client_no_auth()
    basis = str(client.make_url("")).rstrip("/")
    hass.config.media_dirs = {"local": str(tmp_path)}
    (tmp_path / "omroep").mkdir()
    (tmp_path / "omroep" / "test bericht.mp3").write_bytes(b"ID3" + b"\0" * 200)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Nep tuner",
        unique_id="127.0.0.1",
        data={"host": "127.0.0.1", "pin": "1234"},
        options={"pin": "1234", "basis_url": basis},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_config_flow(hass: HomeAssistant, nep) -> None:
    res = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert res["type"] == "form"
    res = await hass.config_entries.flow.async_configure(res["flow_id"], {"host": "127.0.0.1", "pin": "0000"})
    assert res["errors"] == {"base": "niet_bereikbaar"}
    res = await hass.config_entries.flow.async_configure(res["flow_id"], {"host": "127.0.0.1", "pin": "1234"})
    assert res["type"] == "create_entry"
    assert res["title"] == "Nep tuner"


async def test_omroep_herstelt_dab_en_volume(hass: HomeAssistant, ingesteld, nep) -> None:
    antwoord = await hass.services.async_call(
        DOMAIN,
        "omroep",
        {"bericht": "media-source://media_source/local/omroep/test bericht.mp3", "volume": 32, "herhalingen": 2, "pauze": 0.2},
        blocking=True,
        return_response=True,
    )
    assert antwoord["gespeeld"] == 2 and antwoord["fouten"] == []
    assert antwoord["hersteld"] is True
    assert nep.volume_tijdens_bericht == [32, 32]
    assert len(nep.gespeeld) == 2 and "/api/btx_omroep/bestand/" in nep.gespeeld[0]
    assert nep.opgehaald == [200, 200], "tuner moet het bestand echt kunnen ophalen"
    assert nep.luide_radio is False, "radio mag nooit even op omroepvolume spelen"
    assert nep.gespeeld[0].endswith("/test%20bericht.mp3")
    # radio terug zoals voordien
    assert (nep.mode, nep.zender, nep.status) == (5, "VRT StuBru", 2)
    assert nep.volume == 25, "volume moet terug op de oorspronkelijke waarde"
    assert nep.mute == 0
    staat = hass.states.get("sensor.nep_tuner_omroep_status")
    assert staat.state == "klaar" and staat.attributes["gespeeld"] == 2
    # de geheime link is na het bericht niet meer geldig
    assert hass.data[DOMAIN]["bestanden"] == {}


async def test_omroep_kiest_favoriet_als_zender_niet_terugkomt(hass: HomeAssistant, ingesteld, nep) -> None:
    nep.dab_volume_bij_start = 30
    with patch.object(tuner_mod, "STILLE_BRON_IDS", ("BESTAAT_NIET",)):
        antwoord = await hass.services.async_call(
            DOMAIN, "omroep", {"bericht": "omroep/test bericht.mp3"}, blocking=True, return_response=True
        )
    assert antwoord["zender_vanzelf"] is False
    assert (nep.zender, nep.status, nep.volume) == ("VRT StuBru", 2, 25)


async def test_tuner_uit_blijft_uit(hass: HomeAssistant, ingesteld, nep) -> None:
    nep.power = 0
    await hass.services.async_call(DOMAIN, "omroep", {"bericht": "omroep/test bericht.mp3"}, blocking=True)
    assert len(nep.gespeeld) == 1 and nep.power == 0


async def test_bestand_buiten_mediamap_geweigerd(hass: HomeAssistant, ingesteld) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "omroep", {"bericht": "../../etc/passwd"}, blocking=True)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "omroep", {"bericht": "omroep/bestaat_niet.mp3"}, blocking=True)


async def test_bestand_view(hass: HomeAssistant, ingesteld, hass_client_no_auth, tmp_path) -> None:
    from custom_components.btx_omroep import Bestand

    client = await hass_client_no_auth()
    pad = tmp_path / "omroep" / "test bericht.mp3"
    assert (await client.get("/api/btx_omroep/bestand/geheim/x.mp3")).status == 404
    hass.data[DOMAIN]["bestanden"]["geheim"] = Bestand(pad)
    r = await client.head("/api/btx_omroep/bestand/geheim/x.mp3")
    assert r.status == 200
    r = await client.get("/api/btx_omroep/bestand/geheim/x.mp3")
    assert r.status == 200 and await r.read() == pad.read_bytes()


@pytest.mark.parametrize(
    ("tijd", "variabelen", "verwacht"),
    [
        ("2026-10-07 10:00:00", {"modus": "tijden", "tijden": "10:00, 12:30"}, True),
        ("2026-10-07 12:30:00", {"modus": "tijden", "tijden": "10:00,12:30"}, True),
        ("2026-10-07 09:05:00", {"modus": "tijden", "tijden": "9:05"}, True),
        ("2026-10-07 10:01:00", {"modus": "tijden", "tijden": "10:00"}, False),
        ("2026-10-11 10:00:00", {"modus": "tijden", "tijden": "10:00"}, False),  # zondag
        ("2026-10-07 08:00:00", {"modus": "interval"}, True),
        ("2026-10-07 08:30:00", {"modus": "interval"}, True),
        ("2026-10-07 08:15:00", {"modus": "interval"}, False),
        ("2026-10-07 07:30:00", {"modus": "interval"}, False),
        ("2026-10-07 17:00:00", {"modus": "interval"}, True),
        ("2026-10-07 17:30:00", {"modus": "interval"}, False),
        ("2026-10-07 12:30:00", {"modus": "tijden", "tijden": "10:00 12:30"}, True),
        ("2026-10-07 09:05:00", {"modus": "tijden", "tijden": "9:05;10:00"}, True),
        ("2026-10-07 10:00:00", {"modus": "tijden", "tijden": "10:00:00"}, True),
        ("2026-10-07 10:00:00", {"modus": "tijden", "tijden": ""}, False),
        ("2026-10-07 23:00:00", {"modus": "interval", "start": "22:00:00", "einde": "02:00:00"}, True),
        ("2026-10-08 01:30:00", {"modus": "interval", "start": "22:00:00", "einde": "02:00:00"}, True),
        ("2026-10-08 02:30:00", {"modus": "interval", "start": "22:00:00", "einde": "02:00:00"}, False),
        ("2026-10-07 21:30:00", {"modus": "interval", "start": "22:00:00", "einde": "02:00:00"}, False),
        ("2026-10-07 10:00:00", {"modus": "tijden", "weekdagen": []}, False),
    ],
)
async def test_blueprint_planning(hass: HomeAssistant, freezer, tijd, variabelen, verwacht) -> None:
    await hass.config.async_set_time_zone("Europe/Brussels")
    freezer.move_to(f"{tijd}+02:00")
    bp = load_yaml(ROOT / "blueprints/automation/btx_omroep/omroep_planning.yaml")
    tekst = bp["conditions"][0]["value_template"]
    standaard = {
        "weekdagen": ["mon", "tue", "wed", "thu", "fri"],
        "interval": 30,
        "start": "08:00:00",
        "einde": "17:00:00",
        "tijden": "10:00",
    }
    uitkomst = Template(tekst, hass).async_render({**standaard, **variabelen})
    assert uitkomst is verwacht


async def test_blueprint_is_geldig(hass: HomeAssistant) -> None:
    from homeassistant.components.automation.config import async_validate_config_item
    from homeassistant.components.blueprint import models
    from homeassistant.components.blueprint.schemas import BLUEPRINT_SCHEMA

    bp = models.Blueprint(
        load_yaml(ROOT / "blueprints/automation/btx_omroep/omroep_planning.yaml"),
        expected_domain="automation",
        schema=BLUEPRINT_SCHEMA,
    )
    invoer = models.BlueprintInputs(
        bp,
        {
            "use_blueprint": {
                "path": "btx_omroep/omroep_planning.yaml",
                "input": {"bericht": {"media_content_id": "media-source://media_source/local/a.mp3", "media_content_type": "audio/mpeg"}},
            }
        },
    )
    invoer.validate()
    config = invoer.async_substitute()
    assert config["variables"]["volume"] == 32 and config["variables"]["weekdagen"][0] == "mon"
    assert config["actions"][0]["action"] == "btx_omroep.omroep"
    gevalideerd = await async_validate_config_item(hass, "test", {"id": "x", **config})
    assert gevalideerd is not None


async def test_blueprint_actie_geeft_juiste_data(hass: HomeAssistant) -> None:
    from homeassistant.helpers.script import Script
    from pytest_homeassistant_custom_component.common import async_mock_service

    oproepen = async_mock_service(hass, "btx_omroep", "omroep")
    bp = load_yaml(ROOT / "blueprints/automation/btx_omroep/omroep_planning.yaml")
    bericht = {"media_content_id": "media-source://media_source/local/a.mp3", "media_content_type": "audio/mpeg"}
    for tuner, verwacht_tuner in (("", None), ("abc123", "abc123")):
        from homeassistant.helpers import config_validation as cv
        script = Script(hass, cv.SCRIPT_SCHEMA(bp["actions"]), "test", "btx_omroep")
        await script.async_run(
            {"bericht": bericht, "volume": 30, "herhalingen": 3, "pauze": 5, "tuner": tuner}, context=Context()
        )
        await hass.async_block_till_done()
        data = oproepen[-1].data
        assert data["bericht"] == bericht and data["volume"] == 30 and data["herhalingen"] == 3 and data["pauze"] == 5.0
        assert (data.get("tuner") or None) == verwacht_tuner


async def test_lege_tuner_kiest_enige_tuner(hass: HomeAssistant, ingesteld, nep) -> None:
    await hass.services.async_call(
        DOMAIN, "omroep", {"tuner": "", "bericht": {"media_content_id": "media-source://media_source/local/omroep/test bericht.mp3"}}, blocking=True
    )
    assert len(nep.gespeeld) == 1



async def test_onbereikbare_basis_url_geeft_fout(hass: HomeAssistant, ingesteld, nep) -> None:
    from homeassistant.exceptions import HomeAssistantError

    hass.config_entries.async_update_entry(ingesteld, options={"pin": "1234", "basis_url": "http://127.0.0.1:9"})
    await hass.async_block_till_done()
    with pytest.raises(HomeAssistantError, match="haalde het bestand niet op"):
        await hass.services.async_call(DOMAIN, "omroep", {"bericht": "omroep/test bericht.mp3"}, blocking=True)
    staat = hass.states.get("sensor.nep_tuner_omroep_status")
    assert staat.state == "fout"
    assert (nep.mode, nep.status, nep.volume, nep.mute) == (5, 2, 25, 0), "radio moet ook na een fout terug zijn"


async def test_herstel_faalt_dan_noodherstel_nooit_gemute(hass: HomeAssistant, ingesteld, nep) -> None:
    nep.faal_modes = {8}  # omweg via AUX faalt telkens
    antwoord = await hass.services.async_call(
        DOMAIN, "omroep", {"bericht": "omroep/test bericht.mp3", "volume": 32}, blocking=True, return_response=True
    )
    assert antwoord["hersteld"] is False and "herstel mislukt" in antwoord["fouten"]
    assert nep.mute == 0 and nep.mode == 5 and nep.volume == 25
    # noodherstel lukte meteen: geen extra pogingen gepland
    assert not any("noodherstel" in str(t) for t in hass._background_tasks)
    assert hass.states.get("sensor.nep_tuner_omroep_status").state == "fout"


async def test_annuleren_tijdens_bericht_herstelt_toch(hass: HomeAssistant, ingesteld, nep) -> None:
    import asyncio

    nep.duur = 2
    taak = hass.async_create_task(
        hass.services.async_call(DOMAIN, "omroep", {"bericht": "omroep/test bericht.mp3", "volume": 32}, blocking=True)
    )
    await asyncio.sleep(1.5)
    assert nep.mode == 4  # bericht speelt
    taak.cancel()
    for _ in range(80):
        await asyncio.sleep(0.25)
        if hass.states.get("sensor.nep_tuner_omroep_status").state != "bezig":
            break
    assert hass.states.get("sensor.nep_tuner_omroep_status").state == "klaar"
    assert (nep.mode, nep.status, nep.volume, nep.mute) == (5, 2, 25, 0)


async def test_twee_berichten_tegelijk_na_elkaar(hass: HomeAssistant, ingesteld, nep) -> None:
    import asyncio

    oproep = {"bericht": "omroep/test bericht.mp3", "volume": 30}
    await asyncio.gather(
        hass.services.async_call(DOMAIN, "omroep", oproep, blocking=True),
        hass.services.async_call(DOMAIN, "omroep", oproep, blocking=True),
    )
    assert len(nep.gespeeld) == 2
    assert (nep.mode, nep.status, nep.volume, nep.mute) == (5, 2, 25, 0), "tweede bericht mag 'MP, volume 30' niet als oude toestand bewaren"


async def test_opties_controleren_pin_en_url(hass: HomeAssistant, ingesteld) -> None:
    res = await hass.config_entries.options.async_init(ingesteld.entry_id)
    res = await hass.config_entries.options.async_configure(res["flow_id"], {"pin": "1234", "basis_url": "192.168.1.10"})
    assert res["errors"] == {"basis_url": "ongeldige_url"}
    res = await hass.config_entries.options.async_configure(res["flow_id"], {"pin": "9999", "basis_url": ""})
    assert res["errors"] == {"base": "niet_bereikbaar"}
    res = await hass.config_entries.options.async_configure(
        res["flow_id"], {"pin": "1234", "basis_url": "http://192.168.1.10:8123/"}
    )
    assert res["type"] == "create_entry" and res["data"]["basis_url"] == "http://192.168.1.10:8123"
