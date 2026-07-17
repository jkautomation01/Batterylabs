# ⚡ BatteryLabs 3-Phase
### De slimste virtuele batterij voor je Home Assistant

**Stel je voor:** je hebt zonnepanelen, een dynamisch energiecontract bij Zonneplan, en je vraagt je elke dag af — laad ik nu, of wacht ik op een goedkoper tarief? Verkoop ik mijn zonneoverschot terug, of spaar ik het op voor de avondpiek? En wat zou ik eigenlijk besparen als ik een thuisbatterij zou installeren?

**BatteryLabs 3-Phase geeft je het antwoord.** Niet als spreadsheet, niet als ruwe schatting — maar als een volwaardige, draaiende simulatie in Home Assistant die elke 5 seconden meedenkt met jouw energieverbruik.

---

## Wat doet het precies?

BatteryLabs simuleert een **fysiek thuisbatterijsysteem van Victron MultiPlus-II omvormers en Pylontech lithium-batterijen** — gebaseerd op echte datasheet-waarden. De integratie leest je P1-meter uit, denkt mee met de actuele en verwachte energieprijzen, en berekent in real-time wat een batterij zou doen als die er stond.

Het resultaat: meer dan **30 sensoren** in je Home Assistant die je precies vertellen hoe je systeem presteert, hoeveel je bespaart, hoe gezond je (virtuele) batterij is — en wat de slimste actie is voor het komende uur.

**Geen batterij nodig om te beginnen.** Simuleer eerst, investeer daarna op basis van echte data.

---

## Waarom BatteryLabs anders is

De meeste energieplugins tellen kWh's en stoppen daar. BatteryLabs gaat verder:

**🔬 Echte hardware, echte fysica**
De simulatie is gebaseerd op de officiële datasheets van Victron en Pylontech. De omvormer derogeert bij hoge temperatuur. De batterij verliest capaciteit bij kou. Het rendement is niet een vaste 95% maar een kwadratische curve — want bij 10% belasting presteert een omvormer nu eenmaal anders dan bij vol vermogen. Zo voelt de simulatie aan als een echte installatie.

**🧠 Een batterij die leert**
De *Smart Pro* modus bouwt over 2 tot 4 weken een profiel op van jouw verbruikspatroon. Dagelijkse routines, weekendgedrag, ochtendpieken en avondpieken — de integratie leert ze allemaal. Vanaf dat moment stuurt de batterij niet meer reactief op de P1-meter, maar **proactief op basis van wat er gaat komen**.

**📈 Prijsoptimalisatie op basis van echte tariefdata**
Met een Zonneplan dynamisch contract weet de integratie de energieprijzen van de komende 48 uur. Goedkope uren (nacht, middagzon), dure uren (ochtend- en avondpiek) — het systeem plant automatisch wanneer te laden, wanneer te ontladen, en wanneer de lading vast te houden voor als het echt nodig is. Zelfs **negatieve prijzen** worden herkend: als het net je betaalt om stroom af te nemen, laad je de batterij.

**☀️ Zon-bewust plannen**
Via de forecast.solar integratie weet het systeem hoeveel productie er morgen verwacht wordt. Weinig zon? Dan laad je vannacht bij goedkoop tarief een buffer op. Veel zon? Dan hoef je niets te doen — de batterij vult zichzelf overdag.

**💶 ROI die je kunt volgen**
Elke euro die de simulatie bespaart wordt bijgehouden. Je ziet live hoeveel je al gespaard hebt, wat de gemiddelde energieprijs was bij ontladen, en wanneer een echte batterijinstallatie zichzelf terugverdiend zou hebben.

---

## Hardware die gesimuleerd wordt

### Omvormer — Victron MultiPlus-II 48V

| Model | Continu vermogen | Laadstroom | Max. rendement |
|---|---|---|---|
| MultiPlus-II 48/3000 | 2400W / fase | 35A | 95% |
| MultiPlus-II 48/5000 | 4000W / fase | 70A | 96% |
| MultiPlus-II 48/8000 | 6400W / fase | 110A | 95% |
| MultiPlus-II 48/10000 | 8000W / fase | 140A | 96% |
| MultiPlus-II 48/15000 | 12000W / fase | 200A | 95% |

De simulatie gebruikt **één unit per fase** — standaard 3-fase opstelling. Alle vermogenslimieten, temperatuurderotering en rendementsberekeningen zijn direct van de officiële Victron datasheet.

### Batterij — Pylontech US-serie (LFP)

| Model | Capaciteit | Bruikbaar | Cycluslevensduur |
|---|---|---|---|
| US2000C | 2.4 kWh | 2.28 kWh | >8.000 cycli |
| US3000C | 3.55 kWh | 3.37 kWh | >8.000 cycli |
| US5000 | 4.8 kWh | 4.56 kWh | >8.000 cycli |

Configureerbaar van 1 tot 16 modules parallel — van 2.4 kWh tot 76.8 kWh. De simulatie modelleert het **vlakke LFP-spanningsprofiel** (het kenmerkende plateau van lithium-ijzerfosfaat), temperatuurcorrectie op capaciteit, en degradatie op basis van ontladingsdiepte.

---

## De vier modi

### 🌿 Eco (Zelfverbruik)
De batterij volgt puur de P1-meter. Overschot van zonnepanelen gaat de batterij in; zodra het huis stroom trekt, levert de batterij. Simpel, stabiel, altijd beschikbaar.

### ⚡ Smart (Dynamic)
Slim reageren op het momentane verbruik per fase. De batterij balanceert per fase en minimaliseert netimport — zonder naar de toekomst te kijken.

### 🔋 Full Charge (Force)
De batterij laadt zo snel mogelijk op tot 100%. Handig voor wanneer er een stroomstoring verwacht wordt, of als je handmatig een volledige lading wilt opbouwen.

### 🤖 Smart Pro (Predictief)
De meest intelligente modus. Combineert jouw verbruiksprofiel, de PV-productieverwachting en de uurprijzen van Zonneplan tot een **24-uursplan**. De integratie besluit zelfstandig wanneer te laden, wanneer te ontladen, wanneer te wachten — met als enig doel: maximale zelfverbruik en minimale energiekosten.

> **Let op:** Smart Pro heeft een leerperiode van minimaal 2 weken nodig. In die tijd draait de integratie automatisch in Smart Dynamic modus. Na 4 weken is het profiel volledig betrouwbaar. Je kunt de voortgang volgen via de *Leerprofiel Voortgang* sensor.

---

## Installatie

### Vereisten
- Home Assistant (Core 2024.1 of nieuwer)
- P1-meter integratie met sensoren voor import én export per fase (L1, L2, L3)
- Een temperatuursensor (buiten of binnen — voor thermische simulatie)
- Een stroomprijs-sensor (bijv. van de Zonneplan of ENTSO-E integratie)

### Stap 1 — Bestanden plaatsen

Kopieer de map `sim_3phase_battery` naar je Home Assistant configuratiemap:

```
/config/custom_components/sim_3phase_battery/
├── __init__.py
├── button.py
├── config_flow.py
├── const.py
├── hardware_profiles.py
├── manifest.json
├── select.py
└── sensor.py
```

### Stap 2 — Herstart Home Assistant

Herstart volledig zodat de integratie herkend wordt.

### Stap 3 — Integratie toevoegen

Ga naar **Instellingen → Apparaten & Diensten → Integratie toevoegen** en zoek op *BatteryLabs 3-Phase*.

### Stap 4 — Configureren

Vul het formulier in:

**P1-sensoren**
Wijs per fase de import- en exportsensor aan. Dit zijn typisch sensoren van je DSMR of Slimme Meter integratie in kW.

**Omgeving**
- *Prijssensor* — de sensor die de huidige energieprijs in €/kWh geeft
- *Temperatuursensor* — een buitentemperatuur of ruimtetemperatuur sensor

**Hardware**
- *Batterijmodel* — kies het Pylontech model dat het dichtst bij jouw situatie past
- *Aantal modules* — hoeveel modules parallel (1–16)
- *Omvormermodel* — kies het Victron MultiPlus-II model

**Instellingen**
- *Minimale SoC* — de ondergrens voor ontladen (aanbevolen: 10%)
- *Update interval* — hoe vaak de simulatie berekend wordt in seconden (standaard: 5s)
- *Systeemkostprijs* — de aanschafwaarde van het systeem in euro, voor ROI-berekening

**Smart Pro (optioneel)**
- *Zonneplan sensor* — de sensor met het `forecast` attribuut voor uurprijzen
- *PV aanwezig* — schakel in als je zonnepanelen hebt
- *Forecast.solar sensor* — de sensor met de verwachte dagproductie in kWh

---

## Sensoren & entiteiten

Na installatie verschijnen alle entiteiten onder één apparaat: **BatteryLabs Systeem**.

### Batterij
| Sensor | Omschrijving |
|---|---|
| SoC | Laadtoestand in % — met attributen over capaciteit en temperatuurcorrectie |
| State of Health | Batterijgezondheid in % — daalt langzaam naarmate cycli worden gemaakt |
| Batterij Cycli | Aantal equivalente volledige laadcycli |
| Batterij Temperatuur | Gesimuleerde celtemperatuur |
| Tijd tot Leeg | Bij huidige ontlaadsnelheid: hoelang gaat de lading mee |
| Tijd tot Vol | Bij huidige laadsnelheid: hoelang duurt volladen |
| DC Spanning | Realistische LFP-spanning gebaseerd op actuele SoC |
| DC Stroom | Actuele laad- of ontlaadstroom |
| Round Trip Efficiency | Werkelijk gemeten efficiëntie over alle cycli |
| Health Check | Tekstuele statusmelding van het BMS |

### Vermogen & energie
| Sensor | Omschrijving |
|---|---|
| Batterij Vermogen Totaal | Totaal batterijvermogen in W (positief = laden) |
| Inverter L1/L2/L3 Vermogen | Vermogen per fase |
| P1 Werkelijk Totaal | Actueel netverbruik vóór batterijcorrectie |
| Netto P1 Totaal/L1/L2/L3 (Sim) | Gesimuleerd netverbruik mét batterij |
| Zon naar Batterij | Hoeveel PV-overschot de batterij ingaat |
| Zon naar Net | Hoeveel PV-overschot wordt teruggeleverd |
| Batterij Geladen/Ontladen Totaal | Energietellers in kWh |

### Financiën
| Sensor | Omschrijving |
|---|---|
| Besparing Totaal | Totale besparing in € — met break-even voortgang als attribuut |
| ROI Percentage | Terugverdienpercentage op basis van systeemkostprijs |
| Verwachte Besparing 24h | Geschatte besparing van het huidige Smart Pro plan |

### Smart Pro
| Sensor | Omschrijving |
|---|---|
| Plan Actie Huidig Uur | Wat de optimizer nu doet en waarom (incl. prijs als attribuut) |
| Plan SoC Doel | De doellading voor dit uur |
| Volgende Actie | Wat er in het volgende uur gepland staat |
| PV Verwacht Vandaag | Totale PV-productie verwacht vandaag in kWh |
| SoH Degradatie Rate | Actuele degradatiesnelheid in % per maand |
| Leerprofiel Voortgang | 0–100% voortgang van het leerproces |

### Statussen & bediening
| Entiteit | Omschrijving |
|---|---|
| Systeem Status | Laden / Ontladen / Standby |
| Inverter L1/L2/L3 Status | Status per fase |
| BatteryLabs Strategie | Dropdown om de modus te kiezen |
| Reset Leerprofiel | Knop om het leerproces opnieuw te starten |

---

## Het leerproces begrijpen

De *Leerprofiel Voortgang* sensor is jouw venster op hoe slim de integratie al is.

```
0% ──────── 50% ─────────────── 100%
  Leren      Actief (beperkt)    Actief (betrouwbaar)
  ~2 weken   2–4 weken           4+ weken
```

Tijdens het leren draait de integratie automatisch in Smart Dynamic modus — je mist dus niets. Zodra 50% bereikt is (alle 168 dag×uur-combinaties minimaal 2 weken gezien), activeert Smart Pro zich. Na 4 weken is het profiel betrouwbaar genoeg voor optimale planning.

**Wanneer resetten?**
- Na een grote verandering in je dagelijkse routine
- Na installatie van extra zonnepanelen of andere apparatuur
- Als je van woning wisselt

Gebruik de *Reset Leerprofiel* knop op het dashboard, of vink de resetoptie aan in de integratie-instellingen. Je besparing, cycli en SoH-data blijven altijd bewaard.

---

## Dashboard tips

### Minimaal dashboard
Voor een snel overzicht zijn deze vier sensoren het meest waardevol:
1. **SoC** — als gauge card (0–100%)
2. **Systeem Status** — als entity card
3. **Plan Actie Huidig Uur** — als markdown card (inclusief attribuut `reden`)
4. **Besparing Totaal** — als statistiek card

### Attributen gebruiken
Veel sensoren hebben rijke attributen. In een *markdown card* kun je ze tonen:

```yaml
type: markdown
content: >
  **Waarom deze actie?**
  {{ state_attr('sensor.batterylabs_plan_actie_huidig_uur', 'reden') }}

  **Prijs nu:** € {{ state_attr('sensor.batterylabs_plan_actie_huidig_uur', 'prijs_huidig_uur_eur') }}/kWh
  **Duurste uur vandaag:** {{ state_attr('sensor.batterylabs_plan_actie_huidig_uur', 'duurste_uur_vandaag') }}
```

### Automatisering op basis van de optimizer
De *Plan Actie* sensor leent zich perfect voor automations:

```yaml
automation:
  - alias: "Melding bij negatieve energieprijs"
    trigger:
      - platform: state
        entity_id: sensor.batterylabs_plan_actie_huidig_uur
        to: "Laden (negatieve prijs)"
    action:
      - service: notify.mobile_app
        data:
          message: "⚡ Negatieve stroomprijs! Batterij laadt nu gratis op."
```

---

## Veelgestelde vragen

**Heeft dit invloed op mijn echte installatie?**
Nee. BatteryLabs is een pure simulatie — het leest alleen sensordata en schrijft naar Home Assistant entiteiten. Er wordt geen hardware aangestuurd.

**Ik heb geen Zonneplan contract. Werkt het dan ook?**
Ja, volledig. Kies bij de installatie *Vast tarief* als contracttype en vul je kWh-prijs in. De Smart Pro optimizer gebruikt dan tijdsblokken (nacht/ochtendpiek/dag/avondpiek) in plaats van uurprijzen om te beslissen wanneer te laden en ontladen. Je profiteert volledig van het leerproces, de PV-forecast en alle sensoren. De tijdsblokken zijn ook configureerbaar als je thuis een ander dag-patroon hebt dan het standaard.

**Wat is het verschil tussen dynamisch en vast contract bij Smart Pro?**
Bij een dynamisch contract stuurt de optimizer op de werkelijke prijsverschillen per uur — tot 60–70% verschil tussen het goedkoopste en duurste uur. Bij een vast contract stuurt de optimizer op tijdspatroon: nacht en dal zijn "goedkoop", ochtend- en avondpiek zijn "duur". Het effect is hetzelfde: de batterij laadt wanneer het slim is en ontlaadt wanneer het nodig is. De besparing is iets kleiner omdat er geen echte prijsarbitrage is, maar het zelfverbruik en de vermeden netimport-besparing zijn identiek.

**Ik heb geen zonnepanelen. Heeft Smart Pro dan zin?**
Absoluut. Zonder PV optimaliseert de integratie puur op basis van het verbruiksprofiel en de tariefverschillen. Op een dynamisch contract is er altijd een verschil van 30–60% tussen het goedkoopste en duurste uur van de dag.

**Hoe nauwkeurig is de besparing?**
De besparing wordt berekend op basis van werkelijk vermeden netimport × actuele prijs op dat moment. Dit is een conservatieve, realistische berekening — geen marketingcijfers.

**Kan ik meerdere instanties draaien?**
Ja. Je kunt de integratie meerdere keren toevoegen voor verschillende systeemconfiguraties of om scenario's te vergelijken.

**Mijn P1-sensoren geven waarden in W, niet kW. Wat moet ik doen?**
De integratie verwacht kW. Maak een `template sensor` in HA die de waarde door 1000 deelt, en wijs die aan in de configuratie.

---

## Technische details

### Bestanden
| Bestand | Functie |
|---|---|
| `hardware_profiles.py` | Datasheet-profielen Pylontech & Victron |
| `sensor.py` | Coordinator, simulatielogica, alle sensoren |
| `config_flow.py` | Configuratieformulier (aanmaken & bewerken) |
| `select.py` | Strategiedropdown |
| `button.py` | Reset leerprofiel knop |
| `const.py` | Alle constanten en drempelwaarden |

### Opgeslagen bestanden
De integratie schrijft twee bestanden naar je HA config-map:

- `sim_battery_{id}.json` — SoC, SoH, besparing, energietellers (elke 10 minuten)
- `sim_battery_{id}_profile.json` — verbruiksprofiel (elke 30 minuten)

### Versiehistorie
| Versie | Highlights |
|---|---|
| 4.0.0 | Smart Pro optimizer, leerproces, hardware profielen, attribuutlaag |
| 3.0.0 | Bugfixes, async I/O, per-fase sim_p sensoren, cleanup bij unload |
| 2.0.0 | 3-fase ondersteuning, financiële sensoren, thermisch model |

---

## Licentie & credits

Ontwikkeld door **Jordy Kleian**.

Hardwareprofielen gebaseerd op officiële datasheets van [Victron Energy](https://www.victronenergy.com) en [Pylontech](https://en.pylontech.com.cn). BatteryLabs 3-Phase is niet gelieerd aan of goedgekeurd door Victron Energy of Pylontech.

---

*BatteryLabs 3-Phase — omdat slimme energie begint met slim inzicht.*
