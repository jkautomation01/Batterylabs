# BatteryLabs 3-Phase

![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5?style=for-the-badge&logo=homeassistantcommunitystore)
![Version](https://img.shields.io/badge/version-5.0.0-blue?style=for-the-badge)
![License](https://img.shields.io/badge/license-Apache%202.0-green?style=for-the-badge)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.6%2B-41BDF5?style=for-the-badge&logo=homeassistant)

A full software simulation and optimization engine for a 3-phase home battery system (Pylontech US-series + Victron MultiPlus-II), driven entirely by your live smart meter data — configured with just a handful of settings, like a real battery-plus-inverter product.

## Introduction & Features

BatteryLabs 3-Phase does not talk to physical battery hardware — it **simulates** a complete 3-phase battery system in software, and calculates in real time what a real system *should* do: when to charge, when to discharge, and how deep, given your actual household consumption and current electricity prices. It is designed for anyone who wants to model, validate, or forecast battery behavior before (or instead of) buying physical hardware, or who wants a research-grade optimizer running as a "shadow" alongside a planned purchase.

**Key features:**
- 🧮 **Mathematically optimal planning** via dynamic programming — not a greedy rule-of-thumb, but a true cost-minimizing charge/discharge schedule across the full price forecast horizon (hourly or quarter-hourly, whatever your price sensor provides)
- 💡 **Economic wear-cost model** — instead of a hand-set cycle budget, every discharge decision is weighed against the real cost of battery wear (derived from your battery model's replacement cost and degradation curve), so the optimizer cycles less on small price spreads and more on large ones, automatically
- 🔌 **Feed-in tariff awareness** — values unused solar surplus against a configurable feed-in price, so it keeps working correctly even after net-metering (saldering) is phased out
- 🤖 **Built-in system advisor** — continuously compares your configured hardware against all supported alternatives and gives concrete, numbers-backed upgrade suggestions
- ⚡ **Realtime peak shaving** with hysteresis to avoid on/off pendulum behavior
- 🌡️ **Thermal modeling** for both battery and inverter, with temperature-dependent power derating
- 📊 **Self-learning consumption profile** (7×24 EMA matrix) that improves planning accuracy over weeks
- ☀️ **Real hourly solar forecasts** — pulls genuine hour-by-hour PV predictions from the `forecast.solar` service when available, falling back to a Gaussian-curve estimate otherwise
- 🎯 **Forecast self-correction** — continuously compares its own PV and consumption predictions against what actually happened, and learns an hour-by-hour correction factor that keeps improving accuracy over time
- 🧭 **Commercial-style sensor set** — only what a sealed battery/inverter product (Tesla Powerwall, Sigenergy, AlphaESS-style) would show is created by default: SoC, power, status, State of Health, time-to-full/empty, savings and ROI. Every diagnostic/simulator-only sensor (DC values, per-phase inverter detail, the advisor/score engine, forecast-learning accuracy, etc.) is removed entirely, not just hidden
- 🛡️ **Fail-safe by design** — if the optimizer errors out for any reason, the system automatically falls back to a proven heuristic instead of stalling

## Requirements

- Home Assistant 2026.6.x or newer
- Six P1 smart meter power sensors (import + export in kW, per phase — L1/L2/L3)
- Optional: a dynamic energy price sensor with an hourly `forecast` attribute (tested with Zonneplan) — without one, or whenever it has no usable forecast, the system simply uses your configured fixed price
- Optional: a `forecast.solar` sensor for real hourly PV forecasts
- No external Python dependencies (no `scipy` required) — pure standard library

## Installation

### Via HACS (recommended)
1. Open **HACS → Integrations → ⋮ → Custom repositories**
2. Add your repository URL, category **Integration**
3. Search for "BatteryLabs 3-Phase" in HACS and click **Download**
4. Restart Home Assistant

### Manual installation
1. Download or clone this repository
2. Copy the `custom_components/sim_3phase_battery` folder into your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

Configuration is done **entirely through the UI** — no YAML required.

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for "BatteryLabs 3-Phase"
3. Follow the setup wizard (4 steps):
   - **Sensors** — assign your six import/export power sensors (temperature sensor is optional, defaults to 20°C)
   - **Hardware** — select battery model, module count, inverter model, minimum SoC (system cost is optional, defaults to 0 = no ROI calculation)
   - **Energy** — optional price sensor (used automatically if it has an hourly forecast), fixed price, and feed-in tariff
   - **Solar** — optional `forecast.solar` sensor; leave empty if you have no panels

All settings can be changed afterwards via **Settings → Devices & Services → BatteryLabs 3-Phase → Configure**, which opens a menu with each section editable independently.

## Entities & Sensors

Only what a sealed commercial battery/inverter product would expose is created by default:

| Name | Platform | Unit | Description & Interpretation |
|---|---|---|---|
| BatteryLabs SoC | sensor | % | Simulated state of charge. Higher = more stored energy available. |
| BatteryLabs Batterij Vermogen Totaal | sensor | W | Total battery power; positive = charging, negative = discharging. |
| BatteryLabs State of Health | sensor | % | Simulated battery degradation. 100% = new; below 80% triggers a health warning. |
| BatteryLabs Tijd tot Leeg | sensor | text | At the current discharge rate, how long until empty. |
| BatteryLabs Tijd tot Vol | sensor | text | At the current charge rate, how long until full. |
| BatteryLabs Besparing Totaal | sensor | € | Total savings — with break-even progress as an attribute. |
| BatteryLabs ROI Percentage | sensor | % | Payback percentage based on system cost. |
| BatteryLabs Systeem Status | sensor | text | Overall operating state (`Standby`, `Laden`, `Ontladen`). |
| BatteryLabs Strategie | select | — | Mode control: `Automatisch` or `Noodlading (Volladen)`. |

Every sensor exposes additional `attributes` with the underlying calculation detail — click any entity to see exactly why it reports what it does.

A handful of additional sensors stay in the integration **hidden** (not removed) purely because the included Lovelace cards (see below) read them directly — `Actie Nu`, `Actie Reden`, `Plan Actie Huidig Uur`, `Plan SoC Doel`, `Volgende Actie`, `Verwachte Besparing 24h`, `PV Verwacht Vandaag`, `Restcapaciteit`, `Huisreserve SoC` — plus a `Reset Leerprofiel` button for the learning process. They keep updating in the background and can be made visible via **Settings → Devices & Services → Entities** → search "BatteryLabs" → unhide, if you want to use them outside those cards.

Everything else from earlier versions (DC current/voltage, per-phase inverter power/temperature/status, cycle count, round-trip efficiency, health-check text, the advisor/score engine, forecast-learning accuracy, day-spread/arbitrage/DP-cost diagnostics, learning-profile progress) has been **removed entirely** as of 5.0.0 — the underlying calculations still run (they feed the plan/advisor logic internally), there just isn't an entity exposing them anymore.

## Options / Settings

Peak shaving (import threshold and minimum SoC floor) now uses fixed internal defaults (2200 W/phase, 15%) — the adjustable `number` sliders that used to control these were removed along with the rest of the diagnostic entities. Hardware model, price/feed-in settings and the solar forecast sensor are configured through the **Configure** menu described above. There is no manual cycle-budget dial — the optimizer weighs every discharge decision against the real economic cost of battery wear instead (see Key Features above).

## Debugging

To enable verbose debug logging for this integration only, add the following to your `configuration.yaml` and restart Home Assistant:

```yaml
logger:
  default: warning
  logs:
    custom_components.sim_3phase_battery: debug
```

Logs will then appear under **Settings → System → Logs**, filterable by `sim_3phase_battery`.

## Disclaimer & License

This integration is provided "as is", without warranty of any kind. It simulates battery behavior for research, planning, and educational purposes — it does not control physical hardware and is not a substitute for a certified Battery Management System.

Licensed under the [Apache License 2.0](LICENSE).
