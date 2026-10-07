# Btechnics Omroep

HACS integratie `btx_omroep` voor omroepberichten op Frontier Silicon tuners (Hama DIT2105SBTX).
Eerste toepassing: omroep in een magazijn, met Home Assistant op een Raspberry Pi.

## Structuur
- `custom_components/btx_omroep/tuner.py`: kernlogica zonder HA afhankelijkheid (FSAPI + DLNA, herstel)
- `custom_components/btx_omroep/__init__.py`: actie `btx_omroep.omroep`, wachtrij, eenmalige bestandslink
- `custom_components/btx_omroep/coordinator.py` + switch/select/number: radio aan/uit, DAB zender, volume
- `blueprints/automation/btx_omroep/omroep_planning.yaml`: planning per boodschap
- `blueprints/automation/btx_omroep/radio_planning.yaml`: radio aan/uit volgens weekplanning, feestdagen, sluitingen
- `tests/`: nagebootste tuner + tests (`pytest`)

## Afspraken
- Niet testen op de echte tuner zonder uitdrukkelijke toestemming van Matthias
- Testtuner (Hama DIT2105SBTX, firmware V4.5.13): bron DAB key 5, AUX key 8, DMR key 4; IP en PIN staan niet in de repo

## Werkpunten
- [x] Eerste echte test via HA 2026.9.4 (7/10/2026): bericht gespeeld, DAB vanzelf terug, volume en mute correct hersteld (20 s)
- [ ] Mp3 boodschappen van de klant in `/media/omroep/` zetten en luidheid normaliseren (ongeveer -7 LUFS)
- [ ] Radiovolume lager en versterker hoger zetten, zodat boodschappen op 32 duidelijk boven de radio uitkomen
- [ ] Dashboardkaart met knop per boodschap, zenderkeuze, aan/uit en volume
- [x] Op de HA van de klant: schema's zomer (ma tot vr 7:00 tot 17:30) en winter (ma tot vr 7:30 tot 12:00), sensor Magazijn open, Holiday België, kalender Sluitingen, automatisering Radio magazijn aan/uit
- [x] Repo publiek: installatie op de Pi via HACS (aangepaste repository), blueprints importeren via URL
- [x] Automatisch aan/uit met weekplanning, feestdagen en sluitingen (blueprint radio_planning.yaml)
- [x] DAB zender kiezen vanuit HA (keuzelijst favorieten), plus radio aan/uit en volume als entiteiten
- [x] Volgorde mute, DLNA bron, volume, Play werkt op de tuner (getest 7/10/2026)
- [ ] Zender JOE (en andere gebruikte zenders) in de favorieten van de tuner zetten, anders kan herstel via favoriet niet
