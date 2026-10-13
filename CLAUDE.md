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
- [x] Dashboard audio-defrancq aangemaakt (radio, omroep, planning, kalender); visueel nakijken zodra de Pi terug online is
- [x] Intro en outro gong rond elke boodschap (eigen gong, aan/uit te zetten)
- [x] Tekst naar spraak omroepen via Google Translate (tekstvak en knop op dashboard)
- [x] Tekst naar spraak opslaan als vaste boodschap (mp3 in /media/omroep, daarna kiesbaar en inplanbaar)
- [x] Klant kan mp3 boodschappen kiezen en afspelen (keuzelijst uit /media/omroep)
- [x] Uploaden van mp3 niet nodig voor de klant (beslissing Matthias): uploadknop en uitleg van het dashboard gehaald; nieuwe boodschappen via tekst opslaan
- [x] Kalender op dashboard werkt niet volgens Matthias: nakijken, sluitingen toevoegen mogelijk maken
- [x] Op de HA van de klant: openingsuren als 8 input_datetime velden (zomer ma tot vr 7:00 tot 17:30, winter ma tot vr 7:30 tot 17:00, zaterdag gesloten), sensor Magazijn open, Holiday België, kalender Sluitingen, automatisering Radio magazijn aan/uit
- [x] Repo publiek: installatie op de Pi via HACS (aangepaste repository), blueprints importeren via URL
- [x] Automatisch aan/uit met weekplanning, feestdagen en sluitingen (blueprint radio_planning.yaml)
- [x] DAB zender kiezen vanuit HA (keuzelijst favorieten), plus radio aan/uit en volume als entiteiten
- [x] Volgorde mute, DLNA bron, volume, Play werkt op de tuner (getest 7/10/2026)
- [x] Dubbel drukken op Opslaan (iPhone, iPad en desktop): opslaan bij Gereed/Return in naamveld + bevestiging
- [x] Geschiedenis van alle afgespeelde boodschappen (tijd, boodschap, wie, resultaat)
- [x] Tabblad Uitleg op het dashboard
- [x] Tegels Zomer/Winter (schakelbaar, toonden allebei "Uit") vervangen door vaste tabel met actief regime en datum van de wissel
- [x] WhatsApp bericht voor Jérome (klant) met mock-ups van het dashboard
- [x] Winteruren op de HA naar 7:30 tot 17:00 gezet (13/10)
- [x] Melding "Unclosed client session": eigen sessie wordt nu gesloten bij afsluiten HA (v0.4.1)
- [x] HACS download 404 (refs/heads/<commit>.zip): vanaf nu met GitHub releases werken (v0.4.1 gepubliceerd); release maken via gh op de Mac, niet vanuit de cloud
- [x] v0.4.1 geïnstalleerd op de HA van de klant (13/10), HACS download werkt via release. Melding Unclosed client session blijft 1x per opstart, ongeveer 45 s na start: niet van btx_omroep (enige sessie blijft open zolang integratie draait) en niet van btechnics_branding (geen sessies); bron nog onbekend
- [x] Openingsuren door klant aan te passen op dashboard (vraag Defrancq 13/10): input_datetime.{zomer,winter}_{ma_tot_vr,zaterdag}_{open,dicht}; zelfde uur = gesloten; binary_sensor.magazijn_open (template helper) daarop gebaseerd; sectie Openingsuren aanpassen + uitleg; oude schedules verwijderd
- [ ] Zender JOE (en andere gebruikte zenders) in de favorieten van de tuner zetten, anders kan herstel via favoriet niet
