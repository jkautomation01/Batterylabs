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
The *Smart Pro* mode builds a profile of your consumption pattern over 2 to 4 weeks. Daily routines, weekend behavior, morning peaks and evening peaks — the integration learns them all. From that point on, the battery no longer reacts purely to the P1 meter, but **proactively anticipates what's coming**.

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

## The four modes

### 🌿 Eco (Self-consumption)
The battery follows the P1 meter purely. Solar surplus goes into the battery; as soon as the house draws power, the battery delivers it. Simple, stable, always available.

### ⚡ Smart (Dynamic)
Reacts intelligently to instantaneous consumption per phase. The battery balances per phase and minimizes grid import — without looking ahead.

### 🔋 Full Charge (Force)
The battery charges to 100% as fast as possible. Handy for when a power outage is expected, or if you manually want to build up a full charge.

### 🤖 Smart Pro (Predictive)
The most intelligent mode. Combines your consumption profile, PV production forecast, and Zonneplan's hourly prices into a **24-hour plan**. The integration independently decides when to charge, when to discharge, when to wait — with the sole goal of maximizing self-consumption and minimizing energy costs.

> **Note:** Smart Pro needs a learning period of at least 2 weeks. During that time, the integration automatically runs in Smart Dynamic mode. After 4 weeks the profile is fully reliable. You can track progress via the *Learning Profile Progress* sensor.

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
├── button.py
├── config_flow.py
├── const.py
├── hardware_profiles.py
├── manifest.json
├── select.py
└── sensor.py
```

### Step 2 — Restart Home Assistant

Restart fully so the integration is recognized.

### Step 3 — Add the integration

Go to **Settings → Devices & Services → Add Integration** and search for *BatteryLabs 3-Phase*.

### Step 4 — Configure

Fill in the form:

**P1 sensors**
Assign the import and export sensor for each phase. These are typically sensors from your DSMR or Smart Meter integration in kW.

**Environment**
- *Price sensor* — the sensor providing the current energy price in €/kWh
- *Temperature sensor* — an outdoor or indoor temperature sensor

**Hardware**
- *Battery model* — choose the Pylontech model closest to your situation
- *Number of modules* — how many modules in parallel (1–16)
- *Inverter model* — choose the Victron MultiPlus-II model

**Settings**
- *Minimum SoC* — the lower bound for discharging (recommended: 10%)
- *Update interval* — how often the simulation is calculated, in seconds (default: 5s)
- *System cost* — the purchase value of the system in euros, for ROI calculation

**Smart Pro (optional)**
- *Zonneplan sensor* — the sensor with the `forecast` attribute for hourly prices
- *PV present* — enable if you have solar panels
- *Forecast.solar sensor* — the sensor with the expected daily production in kWh

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
| Verwachte Besparing 24h | Estimated savings from the current Smart Pro plan |

### Smart Pro
| Sensor | Description |
|---|---|
| Plan Actie Huidig Uur | What the optimizer is doing right now and why (incl. price as attribute) |
| Plan SoC Doel | The target charge level for this hour |
| Volgende Actie | What's planned for the next hour |
| PV Verwacht Vandaag | Total PV production expected today in kWh |
| SoH Degradatie Rate | Current degradation rate in % per month |
| Leerprofiel Voortgang | 0–100% progress of the learning process |

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

While learning, the integration automatically runs in Smart Dynamic mode — so you don't miss out on anything. Once 50% is reached (all 168 day×hour combinations seen for at least 2 weeks), Smart Pro activates. After 4 weeks the profile is reliable enough for optimal planning.

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

**I don't have a Zonneplan contract. Does it still work?**
Yes, fully. Choose *Fixed rate* as the contract type during installation and enter your kWh price. The Smart Pro optimizer then uses time blocks (night/morning peak/day/evening peak) instead of hourly prices to decide when to charge and discharge. You still fully benefit from the learning process, the PV forecast, and all sensors. The time blocks are also configurable if your household follows a different daily pattern than the default.

**What's the difference between a dynamic and a fixed contract with Smart Pro?**
With a dynamic contract, the optimizer steers on actual hourly price differences — up to a 60–70% difference between the cheapest and most expensive hour. With a fixed contract, the optimizer steers on time patterns: night and off-peak are "cheap," morning and evening peaks are "expensive." The effect is the same: the battery charges when it's smart to and discharges when needed. Savings are somewhat lower since there's no real price arbitrage, but the self-consumption and avoided-grid-import savings are identical.

**I don't have solar panels. Does Smart Pro still make sense?**
Absolutely. Without PV, the integration optimizes purely based on the consumption profile and tariff differences. On a dynamic contract there's always a 30–60% difference between the cheapest and most expensive hour of the day.

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
| `hardware_profiles.py` | Datasheet profiles for Pylontech & Victron |
| `sensor.py` | Coordinator, simulation logic, all sensors |
| `config_flow.py` | Configuration form (setup & edit) |
| `select.py` | Strategy dropdown |
| `button.py` | Reset learning profile button |
| `const.py` | All constants and threshold values |

### Stored files
The integration writes two files to your HA config directory:

- `sim_battery_{id}.json` — SoC, SoH, savings, energy counters (every 10 minutes)
- `sim_battery_{id}_profile.json` — consumption profile (every 30 minutes)

### Version history
| Version | Highlights |
|---|---|
| 4.0.0 | Smart Pro optimizer, learning process, hardware profiles, attribute layer |
| 3.0.0 | Bug fixes, async I/O, per-phase sim_p sensors, cleanup on unload |
| 2.0.0 | 3-phase support, financial sensors, thermal model |

---

## License & credits

Developed by **Jordy Kleian**.

Hardware profiles based on official datasheets from [Victron Energy](https://www.victronenergy.com) and [Pylontech](https://en.pylontech.com.cn). BatteryLabs 3-Phase is not affiliated with or endorsed by Victron Energy or Pylontech.

---

*BatteryLabs 3-Phase — because smart energy starts with smart insight.*
