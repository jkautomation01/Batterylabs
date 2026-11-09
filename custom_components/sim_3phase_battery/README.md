# ⚡ BatteryLabs 3-Phase
### The smartest virtual battery for your Home Assistant

**Imagine:** you have solar panels, a dynamic energy contract with Zonneplan, and every day you wonder — should I charge now, or wait for a cheaper rate? Should I sell my solar surplus back, or save it for the evening peak? And what would I actually save if I installed a home battery?

**BatteryLabs 3-Phase gives you the answer.** Not as a spreadsheet, not as a rough estimate — but as a fully-fledged, running simulation in Home Assistant that thinks along with your energy usage every 5 seconds.

---

## What exactly does it do?

BatteryLabs simulates a **physical home battery system made up of Victron MultiPlus-II inverters and Pylontech lithium batteries** — based on real datasheet values. The integration reads your P1 meter, factors in current and forecast energy prices, and calculates in real time what a battery would do if one were installed.

The result: more than **30 sensors** in your Home Assistant that tell you exactly how your system is performing, how much you're saving, how healthy your (virtual) battery is — and what the smartest action is for the coming hour.

**No battery required to get started.** Simulate first, invest later based on real data.

---

## Why BatteryLabs is different

Most energy plugins just count kWh and stop there. BatteryLabs goes further:

**🔬 Real hardware, real physics**
The simulation is based on the official datasheets from Victron and Pylontech. The inverter derates at high temperatures. The battery loses capacity in the cold. Efficiency isn't a fixed 95% but a quadratic curve — because an inverter simply performs differently at 10% load than at full power. This makes the simulation feel like a real installation.

**🧠 A battery that learns**
The integration builds a profile of your consumption pattern over 2 to 4 weeks. Daily routines, weekend behavior, morning peaks and evening peaks — it learns them all. From that point on, the battery no longer reacts purely to the P1 meter, but **proactively anticipates what's coming**. On top of that, a forecast-learning layer compares its own PV and consumption predictions against what actually happened each hour, and keeps correcting itself.

**📈 Price optimization based on real tariff data**
With a Zonneplan dynamic contract, the integration knows energy prices for the next 48 hours. Cheap hours (night, midday sun), expensive hours (morning and evening peaks) — the system automatically plans when to charge, when to discharge, and when to hold the charge for when it's really needed. Even **negative prices** are recognized: if the grid pays you to consume electricity, the battery charges.

**☀️ Sun-aware planning**
Via the forecast.solar integration, the system knows how much production is expected tomorrow. Little sun? Then it charges a buffer overnight at a cheap rate. Lots of sun? Then nothing needs to happen — the battery fills itself during the day.

**💶 ROI you can track**
Every euro the simulation saves is tracked. You can see live how much you've saved so far, what the average energy price was when discharging, and when a real battery installation would have paid for itself.

---

## Hardware being simulated

### Inverter — Victron MultiPlus-II 48V

| Model | Continuous power | Charge current | Max. efficiency |
|---|---|---|---|
| MultiPlus-II 48/3000 | 2400W / phase | 35A | 95% |
| MultiPlus-II 48/5000 | 4000W / phase | 70A | 96% |
| MultiPlus-II 48/8000 | 6400W / phase | 110A | 95% |
| MultiPlus-II 48/10000 | 8000W / phase | 140A | 96% |
| MultiPlus-II 48/15000 | 12000W / phase | 200A | 95% |

The simulation uses **one unit per phase** — a standard 3-phase setup. All power limits, thermal derating, and efficiency calculations come directly from the official Victron datasheet.

### Battery — Pylontech US series (LFP)

| Model | Capacity | Usable | Cycle life |
|---|---|---|---|
| US2000C | 2.4 kWh | 2.28 kWh | >8,000 cycles |
| US3000C | 3.55 kWh | 3.37 kWh | >8,000 cycles |
| US5000 | 4.8 kWh | 4.56 kWh | >8,000 cycles |

Configurable from 1 to 16 modules in parallel — from 2.4 kWh to 76.8 kWh. The simulation models the **flat LFP voltage profile** (the characteristic plateau of lithium iron phosphate), temperature correction on capacity, and degradation based on depth of discharge.

---

## The two modes

BatteryLabs now works like a real battery-plus-inverter product: just two modes, both always active without any "which strategy should I pick" decision to make.

### ⚡ Automatisch (Automatic)
The normal, always-on mode. Combines your consumption profile, PV production forecast, and (if configured) hourly price data into a continuously-updated **optimal plan**, computed by the dynamic-programming optimizer. The integration independently decides when to charge, when to discharge, and when to hold — weighing real battery wear cost against the savings, with the sole goal of maximizing self-consumption and minimizing energy costs. While the learning profile is still young (first 2 weeks), planning leans more on simple price arbitrage; it automatically leans more heavily on your learned consumption pattern as more data comes in, and is fully reliable after 4 weeks. You can track progress via the *Learning Profile Progress* sensor.

### 🔋 Noodlading (Volladen) — Force charge
The battery charges to 100% as fast as possible. Handy for when a power outage is expected, or if you manually want to build up a full charge. Switch back to Automatisch when you're done.

---

## Installation

### Requirements
- Home Assistant (Core 2024.1 or newer)
- P1 meter integration with sensors for import and export per phase (L1, L2, L3)
- A temperature sensor (outdoor or indoor — for thermal simulation)
- An electricity price sensor (e.g. from the Zonneplan or ENTSO-E integration)

### Step 1 — Place the files

Copy the `sim_3phase_battery` folder to your Home Assistant configuration directory:

```
/config/custom_components/sim_3phase_battery/
├── __init__.py
├── advisor.py
├── button.py
├── config_flow.py
├── const.py
├── dp_optimizer.py
├── forecast_learning.py
├── hardware_profiles.py
├── manifest.json
├── number.py
├── select.py
└── sensor.py
```

### Step 2 — Restart Home Assistant

Restart fully so the integration is recognized.

### Step 3 — Add the integration

Go to **Settings → Devices & Services → Add Integration** and search for *BatteryLabs 3-Phase*.

### Step 4 — Configure

A short, 4-step wizard — no hardware degree needed:

**1. Sensors**
Assign the import and export sensor for each phase (typically from your DSMR or Smart Meter integration, in kW). A temperature sensor is optional (defaults to 20°C if left out).

**2. Hardware**
- *Battery model* — choose the Pylontech model closest to your situation
- *Number of modules* — how many modules in parallel (1–16)
- *Inverter model* — choose the Victron MultiPlus-II model
- *Minimum SoC* — the lower bound for discharging (recommended: 10%)
- *System cost* — optional purchase value of the system in euros, for ROI calculation (0 = skip ROI)

**3. Energy**
- *Price sensor* — optional. If it has an hourly `forecast` attribute (tested with Zonneplan), the optimizer automatically plans on real price differences; without one, or whenever it has no usable value, the system simply uses the fixed price below
- *Fixed price* — your €/kWh rate, used whenever there's no live forecast to plan on
- *Feed-in tariff* — what unvalued solar surplus is worth, in €/kWh

**4. Solar**
- *Forecast.solar sensor* — optional. Leave empty if you have no panels; fill it in to get real hourly PV forecasts instead of the Gaussian-curve estimate

---

## Sensors & entities

After installation, all entities appear under one device: **BatteryLabs Systeem**.

### Battery
| Sensor | Description |
|---|---|
| SoC | State of charge in % — with attributes about capacity and temperature correction |
| State of Health | Battery health in % — declines slowly as cycles accumulate |
| Batterij Cycli | Number of equivalent full charge cycles |
| Batterij Temperatuur | Simulated cell temperature |
| Tijd tot Leeg | At the current discharge rate: how long the charge will last |
| Tijd tot Vol | At the current charge rate: how long a full charge takes |
| DC Spanning | Realistic LFP voltage based on current SoC |
| DC Stroom | Current charge or discharge current |
| Round Trip Efficiency | Actually measured efficiency across all cycles |
| Health Check | Textual status message from the BMS |

### Power & energy
| Sensor | Description |
|---|---|
| Batterij Vermogen Totaal | Total battery power in W (positive = charging) |
| Inverter L1/L2/L3 Vermogen | Power per phase |
| P1 Werkelijk Totaal | Current grid usage before battery correction |
| Netto P1 Totaal/L1/L2/L3 (Sim) | Simulated grid usage with battery |
| Zon naar Batterij | How much PV surplus goes into the battery |
| Zon naar Net | How much PV surplus is fed back to the grid |
| Batterij Geladen/Ontladen Totaal | Energy counters in kWh |

### Finance
| Sensor | Description |
|---|---|
| Besparing Totaal | Total savings in € — with break-even progress as an attribute |
| ROI Percentage | Payback percentage based on system cost |
| Verwachte Besparing 24h | Estimated savings from the current optimizer plan |

### Optimizer & planning
| Sensor | Description |
|---|---|
| Plan Actie Huidig Uur | What the optimizer is doing right now and why (incl. price as attribute) |
| Plan SoC Doel | The target charge level for this hour |
| Volgende Actie | What's planned for the next hour |
| DP Verwachte Kosten | Expected net cost for the remaining planning horizon; negative = projected net earnings |
| PV Verwacht Vandaag | Total PV production expected today in kWh — from the real forecast.solar hourly data when configured, otherwise a Gaussian-curve estimate |
| Forecast Leren Samenvatting / Nauwkeurigheid | How well PV and consumption predictions matched reality, and the self-correction learned from it |
| SoH Degradatie Rate | Current degradation rate in % per month |
| Leerprofiel Voortgang | 0–100% progress of the learning process |

Most of the sensors above are **hidden by default** to keep the entity list manageable — only the handful of core sensors (SoC, total battery power, State of Health, total savings, ROI, system status, current action, current-hour plan action, and learning-profile progress) show up out of the box. Every other sensor still exists and keeps updating; enable any of them via **Settings → Devices & Services → Entities**, search for "BatteryLabs", and toggle the ones you want.

### Status & control
| Entity | Description |
|---|---|
| Systeem Status | Charging / Discharging / Standby |
| Inverter L1/L2/L3 Status | Status per phase |
| BatteryLabs Strategie | Dropdown to select the mode |
| Reset Leerprofiel | Button to restart the learning process |

---

## Understanding the learning process

The *Learning Profile Progress* sensor is your window into how smart the integration has become.

```
0% ──────── 50% ─────────────── 100%
  Learning   Active (limited)    Active (reliable)
  ~2 weeks   2–4 weeks           4+ weeks
```

While learning, the optimizer leans more on simple price arbitrage — so you don't miss out on anything. Once 50% is reached (all 168 day×hour combinations seen for at least 2 weeks), the learned consumption profile starts carrying real weight in the plan. After 4 weeks the profile is reliable enough for fully optimal planning.

**When should you reset?**
- After a major change to your daily routine
- After installing extra solar panels or other equipment
- If you move to a different home

Use the *Reset Learning Profile* button on the dashboard, or tick the reset option in the integration settings. Your savings, cycles, and SoH data are always preserved.

---

## Dashboard tips

### Minimal dashboard
For a quick overview, these four sensors are the most valuable:
1. **SoC** — as a gauge card (0–100%)
2. **Systeem Status** — as an entity card
3. **Plan Actie Huidig Uur** — as a markdown card (including the `reden`/reason attribute)
4. **Besparing Totaal** — as a statistics card

### Using attributes
Many sensors have rich attributes. You can display them in a *markdown card*:

```yaml
type: markdown
content: >
  **Why this action?**
  {{ state_attr('sensor.batterylabs_plan_actie_huidig_uur', 'reden') }}

  **Current price:** € {{ state_attr('sensor.batterylabs_plan_actie_huidig_uur', 'prijs_huidig_uur_eur') }}/kWh
  **Most expensive hour today:** {{ state_attr('sensor.batterylabs_plan_actie_huidig_uur', 'duurste_uur_vandaag') }}
```

### Automations based on the optimizer
The *Plan Action* sensor is perfect for automations:

```yaml
automation:
  - alias: "Notify on negative energy price"
    trigger:
      - platform: state
        entity_id: sensor.batterylabs_plan_actie_huidig_uur
        to: "Laden (negatieve prijs)"
    action:
      - service: notify.mobile_app
        data:
          message: "⚡ Negative electricity price! The battery is charging for free right now."
```

---

## Frequently asked questions

**Does this affect my real installation?**
No. BatteryLabs is a pure simulation — it only reads sensor data and writes to Home Assistant entities. No hardware is controlled.

**I don't have a dynamic energy contract. Does it still work?**
Yes, fully. Just leave the price-sensor field empty during setup (or fill in a sensor without an hourly forecast) and enter your fixed kWh price instead. The optimizer then plans purely on your consumption profile and PV forecast rather than hourly price differences — there's no separate "contract type" choice to make, the system detects automatically whether it has a usable price forecast and falls back to your fixed price when it doesn't. You still fully benefit from the learning process, the PV forecast, and all sensors.

**I don't have solar panels. Does it still make sense?**
Absolutely. Without PV, the integration optimizes purely based on the consumption profile and (if configured) price differences. On a dynamic contract there's typically a 30–60% difference between the cheapest and most expensive hour of the day.

**How accurate are the savings?**
Savings are calculated based on actual avoided grid import × the actual price at that moment. This is a conservative, realistic calculation — not marketing numbers.

**Can I run multiple instances?**
Yes. You can add the integration multiple times for different system configurations or to compare scenarios.

**My P1 sensors report values in W, not kW. What should I do?**
The integration expects kW. Create a `template sensor` in HA that divides the value by 1000, and assign that in the configuration.

---

## Technical details

### Files
| File | Function |
|---|---|
| `hardware_profiles.py` | Datasheet profiles for Pylontech & Victron, incl. degradation-per-cycle model |
| `sensor.py` | Coordinator, simulation logic, all sensors |
| `dp_optimizer.py` | Dynamic-programming planner (wear-cost based, hour or quarter-hour resolution) |
| `forecast_learning.py` | EMA self-correction of PV/consumption predictions vs. reality |
| `advisor.py` | Hardware-sizing advisor logic |
| `config_flow.py` | Configuration form (setup & edit) |
| `select.py` | Mode dropdown (Automatisch / Noodlading) |
| `number.py` | Peak-shaving tuning sliders |
| `button.py` | Reset learning profile button |
| `const.py` | All constants and threshold values |

### Stored files
The integration writes two files to your HA config directory:

- `sim_battery_{id}.json` — SoC, SoH, savings, energy counters (every 10 minutes)
- `sim_battery_{id}_profile.json` — consumption profile (every 30 minutes)

### Version history
| Version | Highlights |
|---|---|
| 5.0.0 | Simplified to two modes (Automatisch/Noodlading), economic wear-cost optimizer (replacing the manual cycle budget), real hourly forecast.solar PV data with self-correcting forecast learning, most sensors hidden by default (enable via Settings → Entities) |
| 4.0.0 | Smart Pro optimizer, learning process, hardware profiles, attribute layer |
| 3.0.0 | Bug fixes, async I/O, per-phase sim_p sensors, cleanup on unload |
| 2.0.0 | 3-phase support, financial sensors, thermal model |

---

## License & credits

Developed by **Jordy Kleian**.

Hardware profiles based on official datasheets from [Victron Energy](https://www.victronenergy.com) and [Pylontech](https://en.pylontech.com.cn). BatteryLabs 3-Phase is not affiliated with or endorsed by Victron Energy or Pylontech.

---

*BatteryLabs 3-Phase — because smart energy starts with smart insight.*
