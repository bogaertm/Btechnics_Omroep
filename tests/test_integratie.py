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
    entry.runtime_data.instellingen["muziekje"] = False  # bestaande tests zonder gong; aparte test met gong
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
        ("2026-10-07 10:00:00", {"modus": "tijden", "stil_kalenders": ["calendar.sluitingen"]}, False),
        ("2026-10-07 10:00:00", {"modus": "tijden", "stil_kalenders": ["calendar.leeg"]}, True),
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
        "stil_kalenders": [],
    }
    hass.states.async_set("calendar.sluitingen", "on")
    hass.states.async_set("calendar.leeg", "off")
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



# ------------------------------------------------------------ bediening
async def test_entiteiten_en_bediening(hass: HomeAssistant, ingesteld, nep) -> None:
    assert hass.states.get("switch.nep_tuner_radio").state == "on"
    zender = hass.states.get("select.nep_tuner_dab_zender")
    assert zender.attributes["options"] == ["1. VRT StuBru", "2. VRT MNM", "3. Qmusic"]
    assert zender.state == "1. VRT StuBru"
    volume = hass.states.get("number.nep_tuner_volume")
    assert float(volume.state) == 25 and volume.attributes["max"] == 32

    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.nep_tuner_dab_zender", "option": "3. Qmusic"}, blocking=True
    )
    assert (nep.mode, nep.zender, nep.status) == (5, "Qmusic", 2)
    await hass.async_block_till_done()
    assert hass.states.get("select.nep_tuner_dab_zender").state == "3. Qmusic"

    await hass.services.async_call("number", "set_value", {"entity_id": "number.nep_tuner_volume", "value": 18}, blocking=True)
    assert nep.volume == 18

    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.nep_tuner_radio"}, blocking=True)
    assert nep.power == 0
    await hass.async_block_till_done()
    assert hass.states.get("switch.nep_tuner_radio").state == "off"
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.nep_tuner_radio"}, blocking=True)
    assert nep.power == 1


async def test_zender_kiezen_vanuit_dlna_stand(hass: HomeAssistant, ingesteld, nep) -> None:
    nep.mode, nep.vorige_mode_was_dmr, nep.status, nep.zender = 4, True, 0, ""
    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.nep_tuner_dab_zender", "option": "2. VRT MNM"}, blocking=True
    )
    assert (nep.mode, nep.zender, nep.status) == (5, "VRT MNM", 2)


async def test_volume_tijdens_bericht_wacht_op_herstel(hass: HomeAssistant, ingesteld, nep) -> None:
    import asyncio

    bericht = hass.async_create_task(
        hass.services.async_call(DOMAIN, "omroep", {"bericht": "omroep/test bericht.mp3", "volume": 32}, blocking=True)
    )
    await asyncio.sleep(1)
    await hass.services.async_call("number", "set_value", {"entity_id": "number.nep_tuner_volume", "value": 12}, blocking=True)
    await bericht
    assert nep.volume_tijdens_bericht == [32]
    assert nep.volume == 12, "volumewijziging tijdens een bericht moet na het herstel toegepast worden"


# ------------------------------------------------------------ radio planning
@pytest.fixture
async def radio_planning(hass: HomeAssistant):
    import shutil

    from homeassistant.setup import async_setup_component
    from pytest_homeassistant_custom_component.common import async_mock_service

    doel = Path(hass.config.path("blueprints/automation/btx_omroep"))
    doel.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "blueprints/automation/btx_omroep/radio_planning.yaml", doel)
    oproepen = {
        "aan": async_mock_service(hass, "switch", "turn_on"),
        "uit": async_mock_service(hass, "switch", "turn_off"),
        "zender": async_mock_service(hass, "select", "select_option"),
        "volume": async_mock_service(hass, "number", "set_value"),
    }
    hass.states.async_set("schedule.open", "off")
    hass.states.async_set("calendar.feestdagen", "off")
    hass.states.async_set("calendar.sluitingen", "off")
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "id": "radio",
                "use_blueprint": {
                    "path": "btx_omroep/radio_planning.yaml",
                    "input": {
                        "radio": "switch.nep_tuner_radio",
                        "schema": "schedule.open",
                        "stil_kalenders": ["calendar.feestdagen", "calendar.sluitingen"],
                        "zender_entiteit": "select.nep_tuner_dab_zender",
                        "zender": "1. VRT StuBru",
                        "volume_entiteit": "number.nep_tuner_volume",
                        "volume": 20,
                    },
                },
            }
        },
    )
    await hass.async_block_till_done()
    return oproepen


async def test_radio_planning_aan_en_uit(hass: HomeAssistant, radio_planning, freezer) -> None:
    from datetime import timedelta

    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    import asyncio

    o = radio_planning

    async def laat_lopen() -> None:
        # het script wacht even voor de zender gekozen wordt: tijd vooruit zetten
        for _ in range(3):
            await asyncio.sleep(0)
        freezer.tick(timedelta(seconds=10))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    hass.states.async_set("schedule.open", "on")
    await laat_lopen()
    assert len(o["aan"]) == 1 and o["aan"][0].data["entity_id"] == ["switch.nep_tuner_radio"]
    assert o["zender"][-1].data["option"] == "1. VRT StuBru"
    assert o["volume"][-1].data["value"] == 20

    hass.states.async_set("calendar.sluitingen", "on")  # sluiting begint
    await hass.async_block_till_done()
    assert len(o["uit"]) == 1

    hass.states.async_set("calendar.sluitingen", "off")  # sluiting voorbij, nog binnen openingsuren
    await laat_lopen()
    assert len(o["aan"]) == 2

    hass.states.async_set("schedule.open", "off")
    await hass.async_block_till_done()
    assert len(o["uit"]) == 2


async def test_radio_planning_feestdag_blijft_uit(hass: HomeAssistant, radio_planning) -> None:
    o = radio_planning
    hass.states.async_set("calendar.feestdagen", "on")
    await hass.async_block_till_done()
    hass.states.async_set("schedule.open", "on")  # openingsuur op een feestdag
    await hass.async_block_till_done()
    assert len(o["aan"]) == 0 and len(o["uit"]) == 2


async def test_radio_planning_zonder_kalenders(hass: HomeAssistant, caplog) -> None:
    import shutil

    from homeassistant.setup import async_setup_component
    from pytest_homeassistant_custom_component.common import async_mock_service

    doel = Path(hass.config.path("blueprints/automation/btx_omroep"))
    doel.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "blueprints/automation/btx_omroep/radio_planning.yaml", doel)
    aan = async_mock_service(hass, "switch", "turn_on")
    hass.states.async_set("schedule.open", "off")
    assert await async_setup_component(
        hass,
        "automation",
        {"automation": {"id": "r", "use_blueprint": {"path": "btx_omroep/radio_planning.yaml",
            "input": {"radio": "switch.x", "schema": "schedule.open"}}}},
    )
    await hass.async_block_till_done()
    automaties = hass.states.async_entity_ids("automation")
    assert len(automaties) == 1 and hass.states.get(automaties[0]).state == "on", "blueprint zonder kalenders moet geldig zijn"
    hass.states.async_set("schedule.open", "on")
    await hass.async_block_till_done()
    assert len(aan) == 1



# ------------------------------------------------------------ muziekje, tekst, knoppen
def _naam(url: str) -> str:
    return url.rsplit("/", 1)[-1]


async def test_muziekje_voor_en_na(hass: HomeAssistant, ingesteld, nep) -> None:
    ingesteld.runtime_data.instellingen["muziekje"] = True
    await hass.services.async_call(
        DOMAIN, "omroep", {"bericht": "omroep/test bericht.mp3", "volume": 32, "herhalingen": 2, "pauze": 0.1}, blocking=True
    )
    assert [_naam(u) for u in nep.gespeeld] == ["gong_in.mp3", "test%20bericht.mp3", "test%20bericht.mp3", "gong_uit.mp3"]
    assert nep.opgehaald == [200, 200, 200, 200]
    assert (nep.mode, nep.status, nep.volume, nep.mute) == (5, 2, 25, 0)
    assert hass.data[DOMAIN]["bestanden"] == {}


async def test_muziekje_uit_via_actie(hass: HomeAssistant, ingesteld, nep) -> None:
    ingesteld.runtime_data.instellingen["muziekje"] = True
    await hass.services.async_call(DOMAIN, "omroep", {"bericht": "omroep/test bericht.mp3", "muziekje": False}, blocking=True)
    assert [_naam(u) for u in nep.gespeeld] == ["test%20bericht.mp3"]


async def test_bericht_of_tekst_verplicht(hass: HomeAssistant, ingesteld) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "omroep", {}, blocking=True)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "omroep", {"bericht": "omroep/test bericht.mp3", "tekst": "x"}, blocking=True)


async def test_tekst_naar_spraak(hass: HomeAssistant, ingesteld, nep, tmp_path) -> None:
    from custom_components.btx_omroep import Bestand

    async def nep_tts(hass_, entry, tekst, basis):
        assert tekst == "Pauze over vijf minuten"
        hass_.data[DOMAIN]["bestanden"]["tts"] = Bestand(tmp_path / "omroep" / "test bericht.mp3")
        return basis + "/api/btx_omroep/bestand/tts/spraak.mp3"

    with patch("custom_components.btx_omroep._tts_url", nep_tts):
        antwoord = await hass.services.async_call(
            DOMAIN, "omroep", {"tekst": "Pauze over vijf minuten"}, blocking=True, return_response=True
        )
    assert antwoord["gespeeld"] == 1 and antwoord["bericht"].startswith("tekst: Pauze")
    assert _naam(nep.gespeeld[0]) == "spraak.mp3" and nep.opgehaald == [200]
    assert (nep.mode, nep.status, nep.volume, nep.mute) == (5, 2, 25, 0)


async def test_tekst_opslaan_en_afspelen_via_knoppen(hass: HomeAssistant, ingesteld, nep, tmp_path) -> None:
    import homeassistant.components.tts  # noqa: F401

    async def tts_audio(hass_, media_id):
        return "mp3", b"ID3" + b"\0" * 100

    await hass.services.async_call("text", "set_value", {"entity_id": "text.nep_tuner_omroeptekst", "value": "Het magazijn sluit binnen 10 minuten"}, blocking=True)
    await hass.services.async_call("text", "set_value", {"entity_id": "text.nep_tuner_naam_boodschap", "value": "Sluiting 10 min!"}, blocking=True)
    with patch("homeassistant.components.tts.generate_media_source_id", return_value="media-source://tts/x"), patch(
        "homeassistant.components.tts.async_get_media_source_audio", tts_audio
    ), patch("custom_components.btx_omroep._standaard_tts", return_value="tts.google"):
        await hass.services.async_call("button", "press", {"entity_id": "button.nep_tuner_tekst_opslaan_als_boodschap"}, blocking=True)
    await hass.async_block_till_done()
    assert (tmp_path / "omroep" / "Sluiting 10 min.mp3").is_file()
    keuze = hass.states.get("select.nep_tuner_boodschap")
    assert "Sluiting 10 min.mp3" in keuze.attributes["options"] and keuze.state == "Sluiting 10 min.mp3"

    await hass.services.async_call("number", "set_value", {"entity_id": "number.nep_tuner_volume_boodschap", "value": 28}, blocking=True)
    await hass.services.async_call("button", "press", {"entity_id": "button.nep_tuner_boodschap_afspelen"}, blocking=True)
    assert _naam(nep.gespeeld[-1]) == "Sluiting%2010%20min.mp3"
    assert nep.volume_tijdens_bericht[-1] == 28
    assert (nep.mode, nep.status, nep.volume, nep.mute) == (5, 2, 25, 0)


async def test_keuzelijst_toont_bestanden_omroepmap(hass: HomeAssistant, ingesteld, tmp_path) -> None:
    keuze = hass.states.get("select.nep_tuner_boodschap")
    assert keuze.attributes["options"] == ["test bericht.mp3"]
    (tmp_path / "omroep" / "notities.txt").write_text("geen audio")
    (tmp_path / "omroep" / "Aankondiging.wav").write_bytes(b"RIFF")
    hass.bus.async_fire("btx_omroep_boodschappen_gewijzigd", {})
    await hass.async_block_till_done()
    assert hass.states.get("select.nep_tuner_boodschap").attributes["options"] == ["Aankondiging.wav", "test bericht.mp3"]


async def test_muziekje_schakelaar_en_instellingen_bestaan(hass: HomeAssistant, ingesteld) -> None:
    for eid in (
        "switch.nep_tuner_muziekje_voor_en_na",
        "number.nep_tuner_aantal_keer",
        "number.nep_tuner_volume_boodschap",
        "button.nep_tuner_tekst_omroepen",
        "button.nep_tuner_boodschap_afspelen",
        "text.nep_tuner_omroeptekst",
        "text.nep_tuner_naam_boodschap",
    ):
        assert hass.states.get(eid) is not None, eid



async def test_standaard_stem_in_taal_van_ha(hass: HomeAssistant) -> None:
    from custom_components.btx_omroep import _standaard_tts

    hass.config.language = "nl"
    hass.states.async_set("tts.google_translate_en_com", "unknown")
    hass.states.async_set("tts.google_translate_nl_be", "unknown")
    hass.states.async_set("tts.piper", "unknown")
    assert _standaard_tts(hass) == "tts.google_translate_nl_be"
    hass.config.language = "en"
    assert _standaard_tts(hass) == "tts.google_translate_en_com"
