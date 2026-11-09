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
- 🙈 **Minimal by default** — only the handful of sensors you actually need to see are visible out of the box; every diagnostic/advanced sensor still exists and can be switched on individually via Settings → Entities
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

| Name | Platform | Unit | Description & Interpretation |
|---|---|---|---|
| BatteryLabs SoC | sensor | % | Simulated state of charge. Higher = more stored energy available. |
| BatteryLabs Batterij Vermogen Totaal | sensor | W | Total battery power; positive = charging, negative = discharging. |
| BatteryLabs Batterij DC Stroom / Spanning | sensor | A / V | Simulated DC current and voltage based on the SoC-voltage curve. |
| BatteryLabs State of Health | sensor | % | Simulated battery degradation. 100% = new; below 80% triggers a health warning. |
| BatteryLabs Batterij Cycli | sensor | count | Cumulative equivalent full cycles since installation. |
| BatteryLabs Health Check | sensor | text | Overall health status (`Healthy`, `Warning: Overheating`, `Caution: Low Battery`, etc.). Anything other than `Healthy` deserves attention. |
| BatteryLabs Round Trip Efficiency | sensor | % | Lifetime charge/discharge efficiency. Lower than ~90% may indicate a modeling or configuration issue. |
| BatteryLabs Batterij Temperatuur | sensor | °C | Simulated cell temperature. Outside 15–35°C reduces available capacity and power. |
| BatteryLabs Inverter L1/L2/L3 Vermogen | sensor | W | Per-phase inverter power; sign convention same as total power. |
| BatteryLabs Actie Nu / Actie Reden | sensor | text | Human-readable explanation of what the system is doing right now and why — the fastest way to understand current behavior. |
| BatteryLabs Plan Actie Huidig Uur | sensor | text | What the 24h optimizer plan prescribes for the current hour. |
| BatteryLabs Plan SoC Doel | sensor | % | Target SoC for the current hour according to the plan. |
| BatteryLabs DP Verwachte Kosten | sensor | € | Expected net cost for the remaining planning horizon, per the DP optimizer. Negative values mean projected net earnings. |
| BatteryLabs Dagspread Prijs | sensor | € | Difference between today's highest and lowest price. Below the configured threshold, the optimizer intentionally holds rather than trades. |
| BatteryLabs Arbitrage Diepte | sensor | % | How deep (in SoC%) the optimizer is willing to cycle per hour, scaled with the daily spread. |
| BatteryLabs Huisreserve SoC | sensor | % | Dynamic floor protecting household consumption from being sold off; never lower than your configured minimum SoC. |
| BatteryLabs Advies Systeem Samenvatting | sensor | text | One-line summary of the single most important improvement opportunity for your system. |
| BatteryLabs Advies Financieel/Omvormer/Capaciteit/Levensduur v2 | sensor | text | Detailed advisor verdicts per dimension, with a numeric score and hardware alternative available as attributes. |
| BatteryLabs Leerprofiel Voortgang | sensor | % | How complete the learned consumption profile is. 100% = fully reliable, used at full weight in planning. |
| BatteryLabs Systeem Score | sensor | 0–100 | Composite health score across six weighted categories. Below 50 suggests attention is warranted. |
| BatteryLabs Systeem Status | sensor | text | Overall operating state (`Standby`, `Laden`, `Ontladen`), with numerous diagnostic attributes. |

Every sensor exposes additional `attributes` with the underlying calculation detail — click any entity to see exactly why it reports what it does.

Most of these sensors are **hidden by default** — only a handful of core sensors (SoC, total battery power, State of Health, total savings, ROI, system status, current action, current-hour plan action, and learning-profile progress) are visible out of the box, to keep the entity list manageable. Every other sensor listed above still exists and keeps updating in the background; enable any of them individually via **Settings → Devices & Services → Entities**, search for "BatteryLabs", and toggle the ones you want to see.

## Options / Settings

Peak shaving stays adjustable live via number sliders, without restarting Home Assistant:

| Setting | Range | Default | Effect |
|---|---|---|---|
| Peak Shaving Drempel | 500–7000 W | 2200 W | Per-phase import power above which the battery discharges to shave the peak. |
| Peak Shaving Min SoC | 5–50% | 15% | Floor below which peak shaving stops and which now also acts as a hard floor for the household reserve. |

There is no manual cycle-budget dial anymore — the optimizer weighs every discharge decision against the real economic cost of battery wear instead (see Key Features above). Hardware model, price/feed-in settings and the solar forecast sensor are configured through the **Configure** menu described above.

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
