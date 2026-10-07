# Btechnics Omroep

Home Assistant integratie voor omroepberichten op een Frontier Silicon tuner
(getest met de Hama DIT2105SBTX). De radio wordt onderbroken, het bericht speelt
via DLNA op de tuner zelf, en daarna komen bron, zender en volume automatisch terug.

## Wat het doet

| Stap | Actie |
|---|---|
| 1 | Toestand bewaren: aan/uit, bron, zender, volume, mute |
| 2 | Volume naar het omroepvolume en het bericht afspelen (1 of meerdere keren, met pauze) |
| 3 | Gemute via AUX terug naar de originele bron |
| 4 | Wachten tot de zender weer speelt, zo nodig de favoriet opnieuw kiezen |
| 5 | Volume terugzetten en controleren, mute eraf, tuner terug uit als hij uit stond |

Berichten wachten op elkaar (wachtrij per tuner). Ook na een fout wordt de radio altijd hersteld.

## Installatie

**Via HACS (aangepaste repository)**
1. HACS → menu rechtsboven → **Aangepaste repositories**
2. URL `https://github.com/bogaertm/Btechnics_Omroep`, type **Integratie**
3. **Btechnics Omroep** installeren en Home Assistant herstarten

De repository is privé: HACS moet aangemeld zijn met een GitHub account dat toegang heeft.
Anders de map `custom_components/btx_omroep` manueel kopiëren naar `/config/custom_components/`.

**Tuner toevoegen**
1. Geef de tuner een vast IP adres in de router
2. Instellingen → Apparaten & diensten → **Integratie toevoegen** → Btechnics Omroep
3. IP adres en PIN (standaard 1234) ingeven

## Gebruik

Zet de mp3 bestanden in de mediamap van Home Assistant (bv. `/media/omroep/`).

```yaml
action: btx_omroep.omroep
data:
  bericht: media-source://media_source/local/omroep/sluiting.mp3
  volume: 32        # 0 tot 32, leeg = huidig volume
  herhalingen: 2    # aantal keer
  pauze: 5          # seconden tussen herhalingen
```

`bericht` mag ook een pad relatief aan de mediamap zijn (`omroep/sluiting.mp3`).

**Planning per boodschap:** importeer de blueprint
`blueprints/automation/btx_omroep/omroep_planning.yaml` en maak per boodschap een
automatisering: vaste uren of elke X minuten, weekdagen, volume, aantal keer en pauze.

**Statussensor:** `sensor.<tuner>_omroep_status` (klaar, bezig, fout) met het laatste resultaat als attributen.

## Netwerk

De tuner haalt het bestand zelf op bij Home Assistant via een eenmalige geheime link.
Tuner en Home Assistant moeten dus in hetzelfde netwerk zitten. Vindt de tuner Home Assistant
niet (bv. bij een reverse proxy of SSL), vul dan in de opties van de integratie de basis URL in,
bv. `http://192.168.1.10:8123`.

## Vastgestelde eigenaardigheden firmware (V4.5.13)

| Gedrag | Oplossing in de integratie |
|---|---|
| DLNA renderer publiceert zijn diensten niet | `/AVTransport/control` op poort 8080 rechtstreeks aanspreken |
| DAB start niet opnieuw na DLNA | Omweg via AUX in, daarna terug naar DAB |
| Tuner zet bij DAB start zijn eigen volume | Volume pas terugzetten als de zender speelt, en nalezen |
| Renderer sluit de verbinding na een bericht | Elke DLNA opdracht op een nieuwe verbinding, met herhaalpoging |

## Tests

```bash
pip install pytest-homeassistant-custom-component
pytest
```

De tests draaien tegen een nagebootste tuner met dezelfde eigenaardigheden; er is geen hardware nodig.
