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

**Via HACS**
1. HACS → menu rechtsboven → **Aangepaste repositories**
2. URL `https://github.com/bogaertm/Btechnics_Omroep`, type **Integratie**
3. **Btechnics Omroep** installeren en Home Assistant herstarten
4. Blueprints importeren: Instellingen → Automatiseringen → Blueprints → **Blueprint importeren** met
   `https://github.com/bogaertm/Btechnics_Omroep/blob/main/blueprints/automation/btx_omroep/omroep_planning.yaml`
   en `https://github.com/bogaertm/Btechnics_Omroep/blob/main/blueprints/automation/btx_omroep/radio_planning.yaml`

**Manueel**: kopieer `custom_components/btx_omroep` naar `/config/custom_components/` en
`blueprints/automation/btx_omroep/` naar `/config/blueprints/automation/`, en herstart Home Assistant.

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

## Muziekje, tekst naar spraak en eigen boodschappen

- **Muziekje**: elke boodschap start met een stijgende gong en eindigt met een dalende gong
  (meegeleverd, eigen aanmaak). Uitschakelen met `switch.<tuner>_muziekje_voor_en_na` of per actie met `muziekje: false`.
- **Tekst naar spraak**: `tekst: "..."` in plaats van `bericht`. Standaard via Google Translate
  (integratie *Google Translate text-to-speech*, taal Nederlands); een andere dienst kies je in de opties.
- **Eigen boodschappen**: zet geluidsbestanden in de mediamap `omroep` (Media → Lokale media → omroep → Uploaden).
  Ze verschijnen binnen 30 s in `select.<tuner>_boodschap`.
- **Tekst bewaren**: vul `text.<tuner>_omroeptekst` en `text.<tuner>_naam_boodschap` in en druk op
  `button.<tuner>_tekst_opslaan_als_boodschap`: de spraak wordt als mp3 in de map `omroep` bewaard en is daarna
  kiesbaar en inplanbaar zoals elke andere boodschap.

## Bediening

| Entiteit | Functie |
|---|---|
| `switch.<tuner>_radio` | Radio aan/uit |
| `select.<tuner>_dab_zender` | DAB zender kiezen uit de favorieten van de tuner (bv. `1. VRT StuBru`) |
| `number.<tuner>_volume` | Volume (0 tot 32) |
| `sensor.<tuner>_omroep_status` | Klaar, bezig of fout, met het laatste resultaat |
| `select.<tuner>_boodschap` | Boodschap kiezen uit de map `omroep` |
| `number.<tuner>_volume_boodschap`, `number.<tuner>_aantal_keer` | Volume en aantal keer voor de knoppen |
| `button.<tuner>_boodschap_afspelen`, `button.<tuner>_tekst_omroepen` | Gekozen boodschap of ingetypte tekst omroepen |
| `switch.<tuner>_muziekje_voor_en_na` | Gong voor en na aan/uit |

Zender, aan/uit en volume wachten tot een lopend omroepbericht klaar is.
De keuzelijst toont de favorieten zoals ze op de tuner staan; nieuwe favorieten
verschijnen binnen 10 minuten zodra de tuner op DAB staat.

## Automatisch aan en uit

Blueprint `radio_planning.yaml`. Benodigd (allemaal standaard in Home Assistant):

| Onderdeel | Waar |
|---|---|
| Weekplanning | Instellingen → Apparaten & diensten → Helpers → **Schema** (openingsuren per dag) |
| Feestdagen | Integratie **Holiday**, land België |
| Sluitingen | Integratie **Lokale kalender**, bv. "Sluitingen"; sluitingsdagen als afspraak toevoegen |

De radio gaat aan bij het begin van een blok in de weekplanning en uit op het einde,
behalve op een feestdag of tijdens een sluiting. Bij het aanzetten kan een vaste zender
en volume gekozen worden. Er wordt enkel geschakeld bij een wijziging in planning of kalender,
dus wie tussendoor manueel schakelt wordt niet meteen overruled.

**Andere uren in zomer- en wintertijd:** maak twee Schema helpers (bv. `schedule.openingsuren_zomer`
en `schedule.openingsuren_winter`) en een template binary sensor (Helpers → Template → Binaire sensor)
met deze toestand, en kies die sensor als weekplanning in de blueprint:

```jinja
{% if now().dst() and now().dst().total_seconds() > 0 %}{{ is_state('schedule.openingsuren_zomer', 'on') }}
{% else %}{{ is_state('schedule.openingsuren_winter', 'on') }}{% endif %}
```

De blueprint voor boodschappen heeft dezelfde optie om niet te spelen tijdens feestdagen en sluitingen.


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
