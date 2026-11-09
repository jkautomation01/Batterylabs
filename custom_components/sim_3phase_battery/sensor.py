import asyncio
import logging
import json
import os
import math
import bisect
import time
from datetime import datetime, timedelta, timezone

from homeassistant.helpers.event import async_track_time_interval, async_track_state_change_event
from homeassistant.helpers import entity_registry as er
from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass
from homeassistant.const import (
    PERCENTAGE, UnitOfPower, UnitOfTemperature,
    CURRENCY_EURO, UnitOfElectricPotential, UnitOfElectricCurrent,
    UnitOfEnergy,
)

from .const import (
    DOMAIN, SAVE_INTERVAL_S, PROFILE_SAVE_INTERVAL_S,
    PROFILE_SLOTS_TOTAL, PROFILE_EMA_ALPHA,
    PROFILE_THRESHOLD_ACTIVE, PROFILE_THRESHOLD_RELIABLE, PROFILE_DAYS_CAP,
    PROFILE_WEEKS_ACTIVE, PROFILE_WEEKS_RELIABLE,
    ZONNEPLAN_PRICE_DIVISOR, PRICE_PERCENTILE_CHEAP, PRICE_PERCENTILE_EXPENSIVE,
    PRICE_NEGATIVE_THRESHOLD, OPTIMIZER_SOC_BUFFER_PCT, OPTIMIZER_PLAN_HORIZON_H,
    OPTIMIZER_SOLAR_SURPLUS_THRESHOLD_W, SOLAR_GAUSS_PEAK_HOUR, SOLAR_GAUSS_SIGMA,
    PRICE_SPREAD_MIN_EUR, PRICE_SPREAD_MAX_EUR, PRICE_SPREAD_MAX_DEPTH_PCT,
    FEED_IN_MODE_FIXED, FEED_IN_MODE_SENSOR, FEED_IN_TARIFF_DEFAULT_EUR,
    DC_VOLTAGE_MIN, POWER_ACTIVE_THRESHOLD_W, INV_THERMAL_RESISTANCE,
    SOH_WARNING_THRESHOLD, TEMP_BAT_WARNING_HIGH, TEMP_BAT_CAUTION_LOW,
    MODE_AUTO, MODE_FORCE, ALL_MODES,
    PROFILE_STATUS_LEARNING, PROFILE_STATUS_ACTIVE_LIMITED, PROFILE_STATUS_ACTIVE_RELIABLE,
    CONTRACT_DYNAMIC, CONTRACT_FIXED, FIXED_CONTRACT_TIME_BLOCKS_DEFAULT,
)
from .hardware_profiles import PYLONTECH_PROFILES, VICTRON_PROFILES
from . import dp_optimizer
from . import advisor as advisor_module
from . import forecast_learning

_LOGGER = logging.getLogger(__name__)


# Begrenst het aantal DP-stappen ongeacht de brondata-resolutie of -horizon.
# 96 stappen = 24u bij kwartierdata (dezelfde horizon als OPTIMIZER_PLAN_HORIZON_H)
# of 96u bij uurdata -- ruim boven de oorspronkelijke ~34 uur, maar begrensd
# zodat de rekentijd nooit ongecontroleerd meegroeit met een langere/fijnere
# forecast-bron.
MAX_DP_PLAN_STEPS = 96


def _detect_step_hours(forecast: list) -> float:
    """Leidt de tijdstap (in klokuren) van een prijs-forecast af uit het
    verschil tussen de eerste twee entries. 1.0 voor uurprijzen, 0.25 voor
    kwartierprijzen. Valt terug op 1.0 (backwards compatible) als er te
    weinig data is of de forecast geen bruikbare timestamps heeft."""
    if not forecast or len(forecast) < 2:
        return 1.0
    try:
        delta = (forecast[1]["hour"] - forecast[0]["hour"]).total_seconds() / 3600.0
    except (KeyError, TypeError):
        return 1.0
    return delta if delta > 0 else 1.0


async def async_setup_entry(hass, config_entry, async_add_entities):
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    sensors = [
        BatterySensor(coordinator, "SoC", "soc", PERCENTAGE, SensorDeviceClass.BATTERY),
        BatterySensor(coordinator, "Batterij Vermogen Totaal", "p_total", UnitOfPower.WATT, SensorDeviceClass.POWER),
        BatterySensor(coordinator, "Batterij DC Stroom", "i_dc", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT, enabled=False),
        BatterySensor(coordinator, "Batterij DC Spanning", "v_dc", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE, enabled=False),
        BatterySensor(coordinator, "State of Health", "soh", PERCENTAGE, None),
        BatterySensor(coordinator, "Batterij Cycli", "cycles", None, None, enabled=False),
        BatteryTextSensor(coordinator, "Health Check", "health_msg", "mdi:heart-pulse", enabled=False),
        BatterySensor(coordinator, "Round Trip Efficiency", "rte", PERCENTAGE, None, enabled=False),
        BatteryTextSensor(coordinator, "Tijd tot Leeg", "time_to_empty", "mdi:battery-clock", enabled=False),
        BatteryTextSensor(coordinator, "Tijd tot Vol", "time_to_full", "mdi:battery-arrow-up-clock", enabled=False),
        BatterySensor(coordinator, "Zon naar Batterij", "solar_to_bat", UnitOfPower.WATT, SensorDeviceClass.POWER, enabled=False),
        BatterySensor(coordinator, "Zon naar Net", "solar_to_grid", UnitOfPower.WATT, SensorDeviceClass.POWER, enabled=False),
        BatterySensor(coordinator, "P1 Werkelijk Totaal", "p_net_real", UnitOfPower.WATT, SensorDeviceClass.POWER, enabled=False),
        BatterySensor(coordinator, "Besparing Totaal", "savings", CURRENCY_EURO, SensorDeviceClass.MONETARY),
        BatterySensor(coordinator, "ROI Percentage", "roi_perc", PERCENTAGE, None),
        BatterySensor(coordinator, "Batterij Geladen Totaal", "energy_in", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, enabled=False),
        BatterySensor(coordinator, "Batterij Ontladen Totaal", "energy_out", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, enabled=False),
        BatterySensor(coordinator, "Inverter L1 Vermogen", "p1", UnitOfPower.WATT, SensorDeviceClass.POWER, enabled=False),
        BatterySensor(coordinator, "Inverter L2 Vermogen", "p2", UnitOfPower.WATT, SensorDeviceClass.POWER, enabled=False),
        BatterySensor(coordinator, "Inverter L3 Vermogen", "p3", UnitOfPower.WATT, SensorDeviceClass.POWER, enabled=False),
        BatterySensor(coordinator, "Netto P1 Totaal (Sim)", "sim_p_total", UnitOfPower.WATT, SensorDeviceClass.POWER, enabled=False),
        BatterySensor(coordinator, "Netto P1 L1 (Sim)", "sim_p1", UnitOfPower.WATT, SensorDeviceClass.POWER, enabled=False),
        BatterySensor(coordinator, "Netto P1 L2 (Sim)", "sim_p2", UnitOfPower.WATT, SensorDeviceClass.POWER, enabled=False),
        BatterySensor(coordinator, "Netto P1 L3 (Sim)", "sim_p3", UnitOfPower.WATT, SensorDeviceClass.POWER, enabled=False),
        BatterySensor(coordinator, "Autarkie Score", "autarky", PERCENTAGE, None, enabled=False),
        BatterySensor(coordinator, "Eigenverbruik Score", "self_consumption", PERCENTAGE, None, enabled=False),
        BatterySensor(coordinator, "Batterij Temperatuur", "t_bat", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, enabled=False),
        BatterySensor(coordinator, "Inverter L1 Temperatuur", "t_inv1", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, enabled=False),
        BatterySensor(coordinator, "Inverter L2 Temperatuur", "t_inv2", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, enabled=False),
        BatterySensor(coordinator, "Inverter L3 Temperatuur", "t_inv3", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, enabled=False),
        BatteryStatusSensor(coordinator),
        BatteryInverterStatusSensor(coordinator, "L1", "inv_l1_stat", enabled=False),
        BatteryInverterStatusSensor(coordinator, "L2", "inv_l2_stat", enabled=False),
        BatteryInverterStatusSensor(coordinator, "L3", "inv_l3_stat", enabled=False),
        BatteryTextSensor(coordinator, "Actie Nu", "actie_uitleg", "mdi:information"),
        BatteryTextSensor(coordinator, "Actie Reden", "actie_reden", "mdi:text-box", enabled=False),
        BatteryTextSensor(coordinator, "Plan Actie Huidig Uur", "plan_action", "mdi:lightning-bolt"),
        BatterySensor(coordinator, "Plan SoC Doel", "plan_soc_target", PERCENTAGE, None, enabled=False),
        BatteryTextSensor(coordinator, "Volgende Actie", "plan_next_action", "mdi:lightning-bolt-outline", enabled=False),
        BatterySensor(coordinator, "Verwachte Besparing 24h", "plan_savings_24h", CURRENCY_EURO, SensorDeviceClass.MONETARY, enabled=False),
        BatterySensor(coordinator, "PV Verwacht Vandaag", "pv_forecast_today_kwh", UnitOfEnergy.KILO_WATT_HOUR, None, enabled=False),
        BatterySensor(coordinator, "SoH Degradatie Rate", "soh_degradation_rate", PERCENTAGE, None, enabled=False),
        BatterySensor(coordinator, "Verwachte Jaarlijkse Besparing", "savings_per_year", CURRENCY_EURO, SensorDeviceClass.MONETARY, enabled=False),
        BatterySensor(coordinator, "Restcapaciteit", "restcapaciteit_kwh", UnitOfEnergy.KILO_WATT_HOUR, None, enabled=False),
        BatterySensor(coordinator, "Huisreserve SoC", "_house_reserve_soc", PERCENTAGE, None, enabled=False),
        BatterySensor(coordinator, "Dagspread Prijs", "day_spread_eur", CURRENCY_EURO, SensorDeviceClass.MONETARY, enabled=False),
        BatterySensor(coordinator, "DP Verwachte Kosten", "dp_expected_cost_eur", CURRENCY_EURO, SensorDeviceClass.MONETARY, enabled=False),
        BatterySensor(coordinator, "Arbitrage Diepte", "_arbitrage_depth_pct", PERCENTAGE, None, enabled=False),
        BatteryProfileSensor(coordinator),
        BatteryTextSensor(coordinator, "Forecast Leren Samenvatting", "forecast_leren_samenvatting", "mdi:school", enabled=False),
        BatterySensor(coordinator, "Forecast Nauwkeurigheid PV", "forecast_leren_pv_nauwkeurigheid", PERCENTAGE, None, enabled=False),
        BatterySensor(coordinator, "Forecast Nauwkeurigheid Verbruik", "forecast_leren_verbruik_nauwkeurigheid", PERCENTAGE, None, enabled=False),
        BatteryTextSensor(coordinator, "Advies Systeem Samenvatting", "advies_systeem_samenvatting", "mdi:robot", enabled=False),
        BatteryTextSensor(coordinator, "Advies Financieel v2", "advies_financieel_v2", "mdi:cash-multiple", enabled=False),
        BatteryTextSensor(coordinator, "Advies Omvormer v2", "advies_omvormer_v2", "mdi:lightning-bolt", enabled=False),
        BatteryTextSensor(coordinator, "Advies Capaciteit v2", "advies_capaciteit_v2", "mdi:battery-charging", enabled=False),
        BatteryTextSensor(coordinator, "Advies Levensduur v2", "advies_levensduur_v2", "mdi:heart-pulse", enabled=False),
        BatterySensor(coordinator,     "Systeem Score",      "score_totaal",     PERCENTAGE, None, enabled=False),
        BatteryTextSensor(coordinator, "Score Klasse",       "score_klasse",     "mdi:gauge", enabled=False),
        BatterySensor(coordinator,     "Score Capaciteit",   "score_capaciteit", PERCENTAGE, None, enabled=False),
        BatterySensor(coordinator,     "Score Omvormer",     "score_omvormer",   PERCENTAGE, None, enabled=False),
        BatterySensor(coordinator,     "Score Rendement",    "score_rte",        PERCENTAGE, None, enabled=False),
        BatterySensor(coordinator,     "Score Financieel",   "score_financieel", PERCENTAGE, None, enabled=False),
        BatterySensor(coordinator,     "Score Gezondheid",   "score_gezondheid", PERCENTAGE, None, enabled=False),
        BatterySensor(coordinator,     "Score EV",           "score_ev",         PERCENTAGE, None, enabled=False),
        BatteryTextSensor(coordinator, "Advies Capaciteit",  "advies_capaciteit",  "mdi:battery-charging", enabled=False),
        BatteryTextSensor(coordinator, "Advies Omvormer",    "advies_omvormer",    "mdi:lightning-bolt", enabled=False),
        BatteryTextSensor(coordinator, "Advies Rendement",   "advies_rte",         "mdi:chart-line", enabled=False),
        BatteryTextSensor(coordinator, "Advies Financieel",  "advies_financieel",  "mdi:cash-multiple", enabled=False),
        BatteryTextSensor(coordinator, "Advies Gezondheid",  "advies_gezondheid",  "mdi:heart-pulse", enabled=False),
        BatteryTextSensor(coordinator, "Advies EV",          "advies_ev",          "mdi:car-electric", enabled=False),
    ]

    async_add_entities(sensors)


class ScoreEngine:
    MIN_DATAPOINTS_SHOW   =   1_440
    MIN_DATAPOINTS_STABLE =  40_320

    ALPHA_FAST   = 0.15
    ALPHA_NORMAL = 0.02
    ALPHA_SHIFT  = 0.08

    ADVICE_CONFIRM_CYCLES =    180
    SHIFT_ZSCORE          = 1.5
    SHIFT_MIN_TICKS       =    720

    CATEGORIES = ["capaciteit", "omvormer", "rte", "financieel", "gezondheid", "ev"]
    WEIGHTS    = {"capaciteit": 0.20, "omvormer": 0.15, "rte": 0.20,
                  "financieel": 0.25, "gezondheid": 0.10, "ev": 0.10}

    def __init__(self):
        self.ewa        = {c: 50.0 for c in self.CATEGORIES}
        self.ewa_m2     = {c: 0.0  for c in self.CATEGORIES}
        self.datapoints = 0

        self.advice_confirmed = {c: "Onvoldoende data" for c in self.CATEGORIES}
        self.advice_candidate = {c: None               for c in self.CATEGORIES}
        self.advice_counter   = {c: 0                  for c in self.CATEGORIES}

        self.shift_counter = {c: 0     for c in self.CATEGORIES}
        self.shift_active  = {c: False for c in self.CATEGORIES}

        self.total_ewa    = 50.0
        self.total_ewa_m2 = 0.0

    def to_dict(self):
        return {
            "ewa": self.ewa, "ewa_m2": self.ewa_m2, "datapoints": self.datapoints,
            "advice_confirmed": self.advice_confirmed, "advice_candidate": self.advice_candidate,
            "advice_counter": self.advice_counter, "shift_counter": self.shift_counter,
            "shift_active": self.shift_active, "total_ewa": self.total_ewa,
            "total_ewa_m2": self.total_ewa_m2,
        }

    def from_dict(self, d):
        if not d: return
        for attr in ["ewa", "ewa_m2", "advice_confirmed", "advice_candidate",
                     "advice_counter", "shift_counter", "shift_active"]:
            if attr in d:
                stored = d[attr]
                target = getattr(self, attr)
                for c in self.CATEGORIES:
                    if c in stored:
                        target[c] = stored[c]
        for attr in ["datapoints", "total_ewa", "total_ewa_m2"]:
            if attr in d:
                setattr(self, attr, d[attr])

    def _raw_scores(self, data, config):
        scores = {}
        cap_kwh = config.get("cap_kwh", 10.0)
        inv_kw  = config.get("inv_kw_per_phase", 3.0)

        soc = data.get("soc", 50.0)
        scores["capaciteit"] = max(0.0, 100.0 - (abs(soc - 50.0) * 0.8))

        limit_w  = inv_kw * 1000
        clipping = any(abs(data.get(f"p{i}", 0.0)) >= limit_w * 0.95 for i in range(1, 4))
        scores["omvormer"] = 60.0 if clipping else 100.0

        rte = data.get("rte", 100.0)
        scores["rte"] = max(0.0, min(100.0, (rte / 94.0) * 100.0))

        roi = data.get("roi_perc", 0.0)
        scores["financieel"] = min(100.0, roi)

        soh     = data.get("soh", 100.0)
        t_bat   = data.get("t_bat", 20.0)
        t_score = 100.0 if 15 <= t_bat <= 35 else max(0.0, 100.0 - abs(t_bat - 25) * 3)
        scores["gezondheid"] = (soh * 0.7) + (t_score * 0.3)

        ev_detected = data.get("ev_detected", False)
        active_min  = data.get("active_min_soc", config.get("min_soc", 10.0))
        ev_reserve  = config.get("ev_reserve_soc", 30.0)
        if ev_detected:
            margin = data.get("soc", 50.0) - active_min
            scores["ev"] = min(100.0, 60.0 + margin * 2)
        else:
            scores["ev"] = 85.0

        return scores

    def _alpha(self, category):
        if self.shift_active[category]:
            return self.ALPHA_SHIFT
        if self.datapoints < self.MIN_DATAPOINTS_SHOW:
            return self.ALPHA_FAST
        if self.datapoints < self.MIN_DATAPOINTS_STABLE:
            t = (self.datapoints - self.MIN_DATAPOINTS_SHOW) / (self.MIN_DATAPOINTS_STABLE - self.MIN_DATAPOINTS_SHOW)
            return self.ALPHA_FAST + t * (self.ALPHA_NORMAL - self.ALPHA_FAST)
        return self.ALPHA_NORMAL

    def _update_ewa(self, category, new_val):
        alpha = self._alpha(category)
        old   = self.ewa[category]
        self.ewa[category] = (1 - alpha) * old + alpha * new_val
        delta = new_val - old
        self.ewa_m2[category] += alpha * (delta ** 2 - self.ewa_m2[category])

    def _detect_shift(self, category, new_val):
        variance = self.ewa_m2[category]
        if variance < 1.0: return
        z = abs(new_val - self.ewa[category]) / math.sqrt(variance)
        if z > self.SHIFT_ZSCORE:
            self.shift_counter[category] += 1
            if self.shift_counter[category] >= self.SHIFT_MIN_TICKS:
                self.shift_active[category] = True
        else:
            self.shift_counter[category] = max(0, self.shift_counter[category] - 1)
            if self.shift_counter[category] == 0:
                self.shift_active[category] = False

    def _advice_text(self, category, score, data, config):
        cap    = config.get("cap_kwh", 10.0)
        inv    = config.get("inv_kw_per_phase", 3.0)
        rte    = data.get("rte", 100.0)
        soh    = data.get("soh", 100.0)
        t      = data.get("t_bat", 20.0)
        roi    = data.get("roi_perc", 0.0)
        soc    = data.get("soc", 50.0)

        if category == "capaciteit":
            if score >= 80:
                return f"Capaciteit {cap:.1f} kWh sluit goed aan bij uw verbruiksprofiel."
            elif score >= 60:
                return f"Capaciteit {cap:.1f} kWh is functioneel maar mogelijk niet optimaal — overweeg patroonanalyse na meer data."
            elif soc > 70:
                return f"Batterij blijft structureel hoog geladen (gem. ~{soc:.0f}% SoC) — {cap:.1f} kWh is waarschijnlijk groter dan nodig."
            else:
                return f"Batterij wordt structureel laag ontladen — {cap:.1f} kWh is mogelijk te klein voor uw verbruik."

        elif category == "omvormer":
            if score >= 80:
                return f"Omvormer vermogen {inv:.1f} kW/fase past goed bij uw vermogensprofiel."
            else:
                return f"Omvormer limiet {inv:.1f} kW/fase wordt regelmatig bereikt (clipping) — overweeg upgrade naar hogere fasecapaciteit."

        elif category == "rte":
            if score >= 85:
                return f"Round-trip rendement {rte:.1f}% is uitstekend voor dit systeemtype."
            elif score >= 70:
                return f"Round-trip rendement {rte:.1f}% is acceptabel — controleer DC-verbindingen op weerstand."
            else:
                return f"Round-trip rendement {rte:.1f}% ligt onder verwachting — mogelijke oorzaak: hoge temperatuur ({t:.1f}°C) of celonbalans."

        elif category == "financieel":
            if score >= 75:
                return f"ROI-trend op koers — {roi:.1f}% terugverdiend. Systeem presteert financieel goed."
            elif score >= 40:
                return f"ROI {roi:.1f}% — terugverdientijd loopt. Optimaliseer laadstrategie voor sneller rendement."
            else:
                return f"ROI {roi:.1f}% — overweeg dynamisch tariefgestuurde sturing om besparingen te maximaliseren."

        elif category == "gezondheid":
            if score >= 85:
                return f"Batterijgezondheid uitstekend: SoH {soh:.0f}%, temperatuur {t:.1f}°C binnen norm."
            elif score >= 65:
                if t > 35:
                    return f"Batterijtemperatuur {t:.1f}°C aan de hoge kant — zorg voor voldoende ventilatie."
                else:
                    return f"SoH {soh:.0f}% — lichte degradatie zichtbaar, normaal na langdurig gebruik."
            else:
                return f"SoH {soh:.0f}% en/of temperatuur {t:.1f}°C vereisen aandacht — overweeg BMS-inspectie."

        elif category == "ev":
            reserve = config.get("ev_reserve_soc", 30.0)
            if score >= 80:
                return f"EV-integratie goed geconfigureerd — home reserve {reserve:.0f}% beschermt huisverbruik effectief."
            else:
                return f"EV-laadpatroon belast thuisbatterij zwaar — overweeg reserve te verhogen boven {reserve:.0f}%."

        return "Geen advies beschikbaar."

    def _update_advice(self, category, score, data, config):
        new_text = self._advice_text(category, score, data, config)
        if new_text == self.advice_confirmed[category]:
            self.advice_candidate[category] = None
            self.advice_counter[category]   = 0
            return
        if new_text == self.advice_candidate[category]:
            self.advice_counter[category] += 1
            if self.advice_counter[category] >= self.ADVICE_CONFIRM_CYCLES:
                self.advice_confirmed[category] = new_text
                self.advice_candidate[category] = None
                self.advice_counter[category]   = 0
        else:
            self.advice_candidate[category] = new_text
            self.advice_counter[category]   = 1

    def update(self, data, config):
        self.datapoints += 1
        raw = self._raw_scores(data, config)
        for cat in self.CATEGORIES:
            self._detect_shift(cat, raw[cat])
            self._update_ewa(cat, raw[cat])
            if self.datapoints >= self.MIN_DATAPOINTS_SHOW:
                self._update_advice(cat, self.ewa[cat], data, config)
        weighted = sum(self.ewa[c] * self.WEIGHTS[c] for c in self.CATEGORIES)
        alpha_t  = self.ALPHA_FAST if self.datapoints < self.MIN_DATAPOINTS_SHOW else self.ALPHA_NORMAL
        self.total_ewa = (1 - alpha_t) * self.total_ewa + alpha_t * weighted

    @property
    def total_score(self):
        return round(self.total_ewa, 1)

    @property
    def score_class(self):
        if self.datapoints < self.MIN_DATAPOINTS_SHOW:
            remaining_h = max(0, (self.MIN_DATAPOINTS_SHOW - self.datapoints) * 60) // 3600
            return f"Lerende fase — nog ~{remaining_h}u data nodig"
        s = self.total_ewa
        if s >= 85: return "Optimaal"
        if s >= 70: return "Goed"
        if s >= 50: return "Matig — verbeteringen mogelijk"
        return "Suboptimaal — actie aanbevolen"

    def sub_scores(self):
        return {c: round(self.ewa[c], 1) for c in self.CATEGORIES}


class BatteryCoordinator:
    def __init__(self, hass, config, entry_id):
        self.hass = hass
        self._config = config
        self._entry_id = entry_id
        self._state_file = hass.config.path(f"sim_battery_{entry_id}.json")
        self._profile_file = hass.config.path(f"sim_battery_{entry_id}_profile.json")
        self._cancel_p1 = None
        self._cancel_slow = None
        self._cancel_timer = None
        self._unsub_event = None
        self._last_save = datetime.now()
        self._last_profile_save = datetime.now()
        self._last_run = datetime.now()
        self._last_slow_run = datetime.now()
        self._last_plan_hour = -1
        self._last_forecast_record_hour = -1

        bat_model = config.get("battery_model", "US5000")
        inv_model = config.get("inverter_model", "MultiPlus-II 48/5000")
        self._bat_profile = PYLONTECH_PROFILES.get(bat_model, PYLONTECH_PROFILES["US5000"])
        self._inv_profile = VICTRON_PROFILES.get(inv_model, VICTRON_PROFILES["MultiPlus-II 48/5000"])
        self._modules = int(config.get("battery_modules", 1))

        self._cap_kwh = self._bat_profile.capacity_kwh * self._modules
        self._cap_wh = self._cap_kwh * 1000
        self._usable_kwh = self._bat_profile.usable_kwh * self._modules

        self._config["cap_kwh"] = self._cap_kwh
        self._config["inv_kw_per_phase"] = self._inv_profile.power_cont_25c_w / 1000.0
        self._config["ev_reserve_soc"] = float(
            config.get("ev_min_soc", config.get("ev_reserve_soc", 30.0))
        )

        self._profile = [[0.0] * 24 for _ in range(7)]
        self._profile_days: list[list[set]] = [[set() for _ in range(24)] for _ in range(7)]

        self._plan: dict = {}
        self._plan_step_hours: float = 1.0
        self._plan_keys_sorted: list = []
        self._dp_building: bool = False
        self._ps_active: bool = False
        self._t_bat_internal: float = 20.0
        self._t_inv_internal: list = [25.0, 25.0, 25.0]
        self._pv_forecast_cache: dict = {}
        self._pv_forecast_fetched_at: datetime = datetime.min

        self.data = {
            "soc": 50.0, "soh": 100.0, "savings": 0.0,
            "energy_in": 0.0, "energy_out": 0.0, "cycles": 0.0,
            "p_total": 0.0, "p1": 0.0, "p2": 0.0, "p3": 0.0, "p_net_real": 0.0,
            "i_dc": 0.0, "v_dc": 52.4,
            "sim_p_total": 0.0, "sim_p1": 0.0, "sim_p2": 0.0, "sim_p3": 0.0,
            "autarky": 0.0, "self_consumption": 0.0,
            "roi_perc": 0.0, "rte": 100.0, "health_msg": "Healthy",
            "solar_to_bat": 0.0, "solar_to_grid": 0.0,
            "time_to_empty": "N.v.t.", "time_to_full": "N.v.t.",
            "t_bat": 20.0, "t_inv1": 25.0, "t_inv2": 25.0, "t_inv3": 25.0,
            "status": "Standby",
            "inv_l1_stat": "Standby", "inv_l2_stat": "Standby", "inv_l3_stat": "Standby",
            "mode": MODE_AUTO,
            "plan_action": "N.v.t.", "plan_soc_target": 50.0,
            "plan_next_action": "N.v.t.", "plan_savings_24h": 0.0,
            "pv_forecast_today_kwh": 0.0, "soh_degradation_rate": 0.0,
            "profile_pct": 0.0, "profile_status": PROFILE_STATUS_LEARNING,
            "profile_days_to_next": PROFILE_WEEKS_ACTIVE * 7,
            "profile_slots_filled": 0, "profile_last_reset": "Nooit",
            "_plan_full": {},
            "_price_now": 0.0,
            "_price_forecast": [],
            "_pv_hourly": [],
            "peak_shaving_threshold_w": 2200.0,
            "peak_shaving_min_soc": 15.0,
            "peak_shaving_actief": False,
            "_house_reserve_soc": 0.0,
            "_arbitrage_depth_pct": 0.0,
            "cycle_budget_per_day": 1.5,
            "use_dp_optimizer": True,
            "dp_expected_cost_eur": 0.0,
            "day_spread_eur": 0.0,
            "arbitrage_actief": False,
            "advies_systeem_samenvatting": "Nog geen advies -- onvoldoende data",
            "advies_financieel_v2": "Onvoldoende data", "advies_omvormer_v2": "Onvoldoende data",
            "advies_capaciteit_v2": "Onvoldoende data", "advies_levensduur_v2": "Onvoldoende data",
            "actie_uitleg": "Opstarten...",
            "actie_reden": "",
            "restcapaciteit_kwh": 0.0,
            "_advisor_days": 0.0,
            "forecast_leren_samenvatting": "Nog aan het leren -- onvoldoende vergelijkingen tussen voorspelling en realiteit.",
            "forecast_leren_pv_nauwkeurigheid": 0.0, "forecast_leren_verbruik_nauwkeurigheid": 0.0,
            "verbruik_forecast_w": [],
            "install_date": datetime.now().strftime("%Y-%m-%d"),
            "score_totaal": 50.0, "score_klasse": "Lerende fase",
            "score_capaciteit": 50.0, "score_omvormer": 50.0, "score_rte": 50.0,
            "score_financieel": 50.0, "score_gezondheid": 50.0, "score_ev": 50.0,
            "advies_capaciteit": "Onvoldoende data", "advies_omvormer": "Onvoldoende data",
            "advies_rte": "Onvoldoende data", "advies_financieel": "Onvoldoende data",
            "advies_gezondheid": "Onvoldoende data", "advies_ev": "Onvoldoende data",
        }

        self._unsub_event = hass.bus.async_listen(
            "sim_battery_mode_changed", self._handle_mode_change
        )
        self._score_engine = ScoreEngine()
        self._advisor_state = advisor_module.AdvisorState()
        self._forecast_learning = forecast_learning.ForecastLearningState()
        self._listeners: list = []

    def set_cancel_timer(self, cancel_p1, cancel_slow=None):
        self._cancel_p1 = cancel_p1
        self._cancel_slow = cancel_slow

    def cancel(self):
        if self._cancel_p1:
            self._cancel_p1()
            self._cancel_p1 = None
        if self._cancel_slow:
            self._cancel_slow()
            self._cancel_slow = None
        if self._cancel_timer:
            self._cancel_timer()
            self._cancel_timer = None
        if self._unsub_event:
            self._unsub_event()
            self._unsub_event = None

    def register_listener(self, callback):
        self._listeners.append(callback)

    def _handle_mode_change(self, event):
        self.data["mode"] = event.data.get("mode")

    async def async_load_data(self):
        def _read():
            if not os.path.exists(self._state_file):
                return None
            try:
                with open(self._state_file, "r") as f:
                    return json.load(f)
            except Exception as exc:
                _LOGGER.warning("BatteryLabs: state lezen mislukt: %s", exc)
                return None

        loaded = await self.hass.async_add_executor_job(_read)
        if loaded:
            self.data.update({k: v for k, v in loaded.items() if k in self.data})
            if "score_engine" in loaded:
                self._score_engine.from_dict(loaded["score_engine"])

        if self.data.get("mode") not in ALL_MODES:
            self.data["mode"] = MODE_AUTO

    async def _async_save_data(self):
        snapshot = {k: self.data[k] for k in (
            "soc", "soh", "savings", "energy_in", "energy_out",
            "t_bat", "roi_perc", "cycles", "mode", "install_date",
            "peak_shaving_threshold_w", "peak_shaving_min_soc",
        )}
        snapshot["score_engine"] = self._score_engine.to_dict()

        def _write():
            try:
                with open(self._state_file, "w") as f:
                    json.dump(snapshot, f)
            except Exception as exc:
                _LOGGER.warning("BatteryLabs: state schrijven mislukt: %s", exc)

        await self.hass.async_add_executor_job(_write)

    async def async_save_state(self):
        await self._async_save_data()

    async def async_load_profile(self):
        def _read():
            if not os.path.exists(self._profile_file):
                return None
            try:
                with open(self._profile_file, "r") as f:
                    return json.load(f)
            except Exception as exc:
                _LOGGER.warning("BatteryLabs: profiel lezen mislukt: %s", exc)
                return None

        loaded = await self.hass.async_add_executor_job(_read)
        if loaded:
            if "profile" in loaded:
                self._profile = loaded["profile"]
            if "profile_days" in loaded:
                self._profile_days = [
                    [set(day_set) for day_set in week_row]
                    for week_row in loaded["profile_days"]
                ]
            if "last_reset" in loaded:
                self.data["profile_last_reset"] = loaded["last_reset"]
            if "forecast_learning" in loaded:
                self._forecast_learning.from_dict(loaded["forecast_learning"])

        self._backfill_advisor_state()

    def _backfill_advisor_state(self):
        """Initialiseert advisor peak-power uit het bestaande verbruiksprofiel."""
        if self._advisor_state.peak_power_l1 > 0:
            return
        all_vals = [v * 1000 for row in self._profile for v in row if v > 0]
        if not all_vals:
            return
        peak_estimate = max(all_vals) * 1.3
        self._advisor_state.peak_power_l1 = peak_estimate / 3
        self._advisor_state.peak_power_l2 = peak_estimate / 3
        self._advisor_state.peak_power_l3 = peak_estimate / 3
        self._advisor_state.peak_power_date = datetime.now().strftime("%Y-%m-%d")
        _LOGGER.info(
            "BatteryLabs: advisor teruggevuld met historisch profiel "
            "(geschat piekvermogen %.0fW per fase)", peak_estimate / 3,
        )

    async def _async_save_profile(self):
        profile_days_serializable = [
            [list(day_set) for day_set in week_row]
            for week_row in self._profile_days
        ]
        snapshot = {
            "profile": self._profile,
            "profile_days": profile_days_serializable,
            "last_reset": self.data["profile_last_reset"],
            "forecast_learning": self._forecast_learning.to_dict(),
        }

        def _write():
            try:
                with open(self._profile_file, "w") as f:
                    json.dump(snapshot, f)
            except Exception as exc:
                _LOGGER.warning("BatteryLabs: profiel schrijven mislukt: %s", exc)

        await self.hass.async_add_executor_job(_write)

    async def async_reset_profile(self):
        self._profile = [[0.0] * 24 for _ in range(7)]
        self._profile_days = [[set() for _ in range(24)] for _ in range(7)]
        self._set_plan({})
        self.data["profile_last_reset"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.data["profile_pct"] = 0.0
        self.data["profile_status"] = PROFILE_STATUS_LEARNING
        self.data["plan_action"] = "N.v.t."
        self.data["plan_soc_target"] = self.data["soc"]

        def _delete():
            try:
                if os.path.exists(self._profile_file):
                    os.remove(self._profile_file)
            except Exception as exc:
                _LOGGER.warning("BatteryLabs: profiel verwijderen mislukt: %s", exc)

        await self.hass.async_add_executor_job(_delete)
        _LOGGER.info("BatteryLabs: leerprofiel gereset op %s", self.data["profile_last_reset"])

    def _format_time(self, hours_decimal):
        if hours_decimal <= 0 or hours_decimal > 240:
            return "N.v.t."
        total_min = int(hours_decimal * 60)
        return f"{total_min // 60}u {total_min % 60}m"

    def _safe_state(self, entity_id: str, fallback: float = 0.0) -> float:
        if not entity_id:
            return fallback
        state_obj = self.hass.states.get(entity_id)
        if state_obj is None:
            _LOGGER.debug("BatteryLabs: entiteit '%s' niet gevonden", entity_id)
            return fallback
        val = state_obj.state
        if val in (None, "unknown", "unavailable", "none"):
            return fallback
        try:
            return float(str(val).replace(",", "."))
        except (ValueError, TypeError):
            _LOGGER.warning("BatteryLabs: '%s' niet naar float: %s", entity_id, val)
            return fallback

    def _safe_attribute(self, entity_id: str, attribute: str, fallback=None):
        if not entity_id:
            return fallback
        state_obj = self.hass.states.get(entity_id)
        if state_obj is None:
            return fallback
        return state_obj.attributes.get(attribute, fallback)

    def _get_feed_in_price(self) -> float:
        """Terugleveringstarief: vast getal of via een gekoppelde sensor."""
        mode = self._config.get("feed_in_mode", FEED_IN_MODE_FIXED)
        if mode == FEED_IN_MODE_SENSOR:
            sensor_id = self._config.get("feed_in_tariff_sensor", "")
            if sensor_id:
                return self._safe_state(sensor_id, fallback=float(self._config.get("feed_in_tariff_eur", FEED_IN_TARIFF_DEFAULT_EUR)))
        return float(self._config.get("feed_in_tariff_eur", FEED_IN_TARIFF_DEFAULT_EUR))

    def _update_profile_progress(self):
        total_slots = 7 * 24
        days_per_slot = [
            len(self._profile_days[d][h])
            for d in range(7)
            for h in range(24)
        ]

        slots_filled = sum(1 for d in days_per_slot if d >= 1)
        self.data["profile_slots_filled"] = slots_filled

        phase1_progress = sum(
            min(d / PROFILE_THRESHOLD_ACTIVE, 1.0) for d in days_per_slot
        ) / total_slots

        phase2_progress = sum(
            min(d / PROFILE_THRESHOLD_RELIABLE, 1.0) for d in days_per_slot
        ) / total_slots

        pct_total = (phase1_progress * 50.0) + (phase2_progress * 50.0)
        self.data["profile_pct"] = round(pct_total, 1)

        if pct_total >= 100.0:
            self.data["profile_status"] = PROFILE_STATUS_ACTIVE_RELIABLE
            self.data["profile_days_to_next"] = 0
        elif phase1_progress >= 1.0:
            self.data["profile_status"] = PROFILE_STATUS_ACTIVE_LIMITED
            avg_days = sum(days_per_slot) / total_slots
            days_remaining = max(0.0, PROFILE_THRESHOLD_RELIABLE - avg_days)
            self.data["profile_days_to_next"] = max(0, round(days_remaining))
        else:
            self.data["profile_status"] = PROFILE_STATUS_LEARNING
            avg_days = sum(days_per_slot) / total_slots
            days_remaining = max(0.0, PROFILE_THRESHOLD_ACTIVE - avg_days)
            self.data["profile_days_to_next"] = max(0, round(days_remaining))

    def _parse_price_forecast(self) -> list:
        sensor_id = self._config.get("zonneplan_sensor", "")
        raw = self._safe_attribute(sensor_id, "forecast", fallback=None)
        if not raw or not isinstance(raw, list):
            return []

        result = []
        for entry in raw:
            try:
                price_raw = entry.get("electricity_price") or (entry.get("price_tax_included") or {}).get("amount", 0)
                price_eur = price_raw / ZONNEPLAN_PRICE_DIVISOR
                dt_raw = entry.get("datetime") or entry.get("start_date", "")
                if isinstance(dt_raw, datetime):
                    dt = dt_raw if dt_raw.tzinfo else dt_raw.replace(tzinfo=timezone.utc)
                else:
                    dt = datetime.fromisoformat(str(dt_raw).replace("Z", "+00:00"))
                result.append({
                    "hour": dt,
                    "price_eur": price_eur,
                    "tariff": entry.get("tariff_group", "normal"),
                    "sustainability": entry.get("sustainability_score") if isinstance(entry.get("sustainability_score"), (int, float)) else (entry.get("sustainability_score") or {}).get("permille", 0),
                    "negative": price_eur < PRICE_NEGATIVE_THRESHOLD,
                })
            except Exception as exc:
                _LOGGER.debug("BatteryLabs: prijsentry overgeslagen: %s", exc)

        result.sort(key=lambda x: x["hour"])
        return result

    def _classify_prices(self, forecast: list) -> dict:
        contract_type = self._config.get("contract_type", CONTRACT_DYNAMIC)

        if contract_type == CONTRACT_FIXED:
            return self._classify_prices_fixed()

        if not forecast:
            _LOGGER.debug("BatteryLabs: geen prijsforecast, tijdsblokken als fallback")
            return self._classify_prices_fixed()

        prices = [e["price_eur"] for e in forecast]
        prices_sorted = sorted(prices)
        n = len(prices_sorted)
        p_cheap = prices_sorted[max(0, int(n * PRICE_PERCENTILE_CHEAP / 100) - 1)]
        p_expensive = prices_sorted[min(n - 1, int(n * PRICE_PERCENTILE_EXPENSIVE / 100))]

        result = {}
        for entry in forecast:
            h = entry["hour"]
            if entry["negative"]:
                cls = "negative"
            elif entry["price_eur"] <= p_cheap:
                cls = "cheap"
            elif entry["price_eur"] >= p_expensive:
                cls = "expensive"
            else:
                cls = "normal"
            result[h] = cls
        return result

    def _classify_prices_fixed(self) -> dict:
        from datetime import timezone as _tz

        raw_blocks = self._config.get("fixed_time_blocks", "")
        if raw_blocks and isinstance(raw_blocks, list):
            blocks = raw_blocks
        else:
            blocks = FIXED_CONTRACT_TIME_BLOCKS_DEFAULT

        hour_cls = {}
        for start, end, cls in blocks:
            for h in range(int(start), int(end)):
                hour_cls[h % 24] = cls

        now_utc = datetime.now(_tz.utc).replace(minute=0, second=0, microsecond=0)
        result = {}
        for offset in range(24):
            dt = now_utc + timedelta(hours=offset)
            local_hour = dt.astimezone().hour
            result[dt] = hour_cls.get(local_hour, "normal")
        return result

    def _get_pv_hourly_forecast(self) -> list:
        if not self._config.get("pv_present", False):
            return [0.0] * 24

        cached = self._pv_forecast_cache.get("hourly_wh") if self._pv_forecast_cache else None
        if cached and sum(cached) > 0:
            return cached

        sensor_id = self._config.get("solar_forecast_sensor", "")
        total_kwh = self._safe_state(sensor_id, fallback=0.0)
        total_wh = total_kwh * 1000

        if total_wh <= 0:
            return [0.0] * 24

        weights = []
        for h in range(24):
            exponent = -((h - SOLAR_GAUSS_PEAK_HOUR) ** 2) / (2 * SOLAR_GAUSS_SIGMA ** 2)
            weights.append(math.exp(exponent))

        total_weight = sum(weights)
        return [(w / total_weight) * total_wh for w in weights]

    async def _refresh_solar_forecast(self, now_local: datetime) -> None:
        """Haalt de echte uur-voor-uur PV-forecast op via de forecast.solar
        service als de gekoppelde sensor van die integratie komt, en cachet
        die voor _get_pv_hourly_forecast(). Hoogstens eens per 30 minuten
        aangeroepen om de service niet te overbelasten. Bij elke fout of als
        de sensor niet van forecast.solar is, blijft de Gauss-curve de
        terugval (cache leeg laten is daarvoor genoeg)."""
        if not self._config.get("pv_present", False):
            return
        if self._pv_forecast_cache and (now_local - self._pv_forecast_fetched_at).total_seconds() < 1800:
            return

        sensor_id = self._config.get("solar_forecast_sensor", "")
        if not sensor_id:
            return

        try:
            entity_entry = er.async_get(self.hass).async_get(sensor_id)
            if entity_entry is None or entity_entry.platform != "forecast_solar" or not entity_entry.config_entry_id:
                return

            response = await self.hass.services.async_call(
                "forecast_solar", "get_forecast",
                {"config_entry": entity_entry.config_entry_id, "resolution": "hourly"},
                blocking=True, return_response=True,
            )
            wh_period = (response or {}).get("wh_period", {})
            today = now_local.date()
            hourly = [0.0] * 24
            for ts_str, wh in wh_period.items():
                try:
                    ts_local = datetime.fromisoformat(ts_str).astimezone()
                except ValueError:
                    continue
                if ts_local.date() == today:
                    hourly[ts_local.hour] = float(wh)

            if sum(hourly) > 0:
                self._pv_forecast_cache = {"hourly_wh": hourly}
                self._pv_forecast_fetched_at = now_local
        except Exception as exc:
            _LOGGER.debug("BatteryLabs: forecast.solar service-call mislukt (%s), val terug op Gauss-curve", exc)

    def _build_plan(self, now_local: datetime, p_net_phases: list,
                    price_forecast: list, profile_weight: float = 1.0) -> dict:
        pv_hourly = self._get_pv_hourly_forecast()
        self.data["_pv_hourly"] = pv_hourly
        self.data["pv_forecast_today_kwh"] = round(sum(pv_hourly) / 1000, 2)

        now_utc = now_local.astimezone(timezone.utc)
        future_forecast = [
            e for e in price_forecast
            if e["hour"] >= now_utc.replace(minute=0, second=0, microsecond=0)
        ]
        if not future_forecast:
            future_forecast = price_forecast

        price_map = {}
        for entry in future_forecast:
            local_hour = entry["hour"].astimezone().hour
            if local_hour not in price_map:
                price_map[local_hour] = entry

        classified = self._classify_prices(future_forecast)
        classified_local = {}
        for dt, cls in classified.items():
            if hasattr(dt, "astimezone"):
                classified_local[dt.astimezone().hour] = cls
            else:
                classified_local[dt] = cls

        cap_wh = self._cap_wh
        min_soc = self._config.get("min_soc", 10.0)
        max_soc = 100.0
        soc_buffer = OPTIMIZER_SOC_BUFFER_PCT

        ps_min_soc = float(self.data.get("peak_shaving_min_soc", 15.0))
        plan_floor_soc = max(min_soc, ps_min_soc)

        tomorrow_pv_kwh = self._config.get("pv_present", False) and \
            self.data.get("pv_forecast_today_kwh", 0.0)
        zon_morgen_voldoende = bool(tomorrow_pv_kwh and float(tomorrow_pv_kwh) > 5.0)

        day_of_week = now_local.weekday()
        all_profile_vals = [v * 1000 for row in self._profile for v in row if v > 0]
        conservative_w = (sum(all_profile_vals) / len(all_profile_vals)
                          if all_profile_vals else 400.0)
        expected_consumption_w = []
        for h in range(24):
            profiel_w = self._profile[day_of_week][h] * 1000
            if profiel_w < 1.0:
                profiel_w = conservative_w * 1.2 if 7 <= h < 22 else conservative_w * 0.6
            mixed_w = profile_weight * profiel_w + (1 - profile_weight) * (
                conservative_w * 1.2 if 7 <= h < 22 else conservative_w * 0.6
            )
            expected_consumption_w.append(mixed_w)

        plan = {}
        day_prices = [e["price_eur"] for e in future_forecast]
        day_spread = (max(day_prices) - min(day_prices)) if day_prices else 0.0
        if day_spread > PRICE_SPREAD_MIN_EUR:
            spread_scale = min(1.0, (day_spread - PRICE_SPREAD_MIN_EUR) / (PRICE_SPREAD_MAX_EUR - PRICE_SPREAD_MIN_EUR))
        else:
            spread_scale = 0.0
        arbitrage_depth_pct = spread_scale * PRICE_SPREAD_MAX_DEPTH_PCT
        current_soc = self.data["soc"]

        for h in range(OPTIMIZER_PLAN_HORIZON_H):
            hour = (now_local.hour + h) % 24
            price_entry = price_map.get(hour, {})
            price_eur = price_entry.get("price_eur", self.data["_price_now"])
            cls = classified_local.get(hour, "normal")
            sustainability = price_entry.get("sustainability", 0)

            expected_w = expected_consumption_w[hour]
            pv_w = pv_hourly[hour] if hour < len(pv_hourly) else 0.0
            net_expected_w = expected_w - pv_w

            if price_eur < PRICE_NEGATIVE_THRESHOLD:
                target_soc = min(max_soc, current_soc + 25.0)
                action = "Laden (negatieve prijs)"
                reason = f"Stroomprijs negatief: €{price_eur:.4f}/kWh — net betaalt voor afname"

            elif cls == "expensive" and current_soc > plan_floor_soc + soc_buffer and arbitrage_depth_pct > 0:
                target_soc = max(plan_floor_soc + soc_buffer, current_soc - arbitrage_depth_pct)
                action = "Ontladen (piekprijs)"
                reason = f"Duurste tariefgroep: €{price_eur:.4f}/kWh, dagspread €{day_spread:.3f} -> diepte {arbitrage_depth_pct:.0f}%"

            elif cls == "expensive" and current_soc > plan_floor_soc + soc_buffer:
                target_soc = current_soc
                action = "Vasthouden (spread te klein)"
                reason = (
                    f"Duur tarief, maar dagspread €{day_spread:.3f} onder drempel "
                    f"€{PRICE_SPREAD_MIN_EUR:.2f} -- arbitrage niet rendabel t.o.v. cyclus-slijtage."
                )
            elif pv_w > OPTIMIZER_SOLAR_SURPLUS_THRESHOLD_W and net_expected_w < 0:
                solar_surplus_wh = abs(net_expected_w)
                soc_gain = (solar_surplus_wh / cap_wh) * 100
                target_soc = min(max_soc, current_soc + soc_gain)
                action = "Laden (zon-overschot)"
                reason = f"PV verwacht {pv_w:.0f}W, overschot {abs(net_expected_w):.0f}W"

            elif cls == "cheap" and not zon_morgen_voldoende:
                target_soc = min(max_soc, current_soc + 15.0)
                action = "Laden (dal-tarief, weinig zon morgen)"
                reason = (
                    f"Goedkoop tarief, PV morgen {float(tomorrow_pv_kwh or 0):.1f} kWh — "
                    f"preventief laden voor avondpiek"
                )

            elif cls == "cheap" and zon_morgen_voldoende:
                target_soc = current_soc
                action = "Vasthouden (zon morgen verwacht)"
                reason = f"Zon morgen {float(tomorrow_pv_kwh):.1f} kWh — PV laadt overdag"

            else:
                target_soc = current_soc
                action = "Vasthouden"
                reason = f"Normaal tarief (€{price_eur:.4f}/kWh) — geen actie"

            target_soc = max(plan_floor_soc, min(max_soc, target_soc))

            plan[hour] = {
                "target_soc": round(target_soc, 1),
                "action": action,
                "reason": reason,
                "price_eur": round(price_eur, 5),
                "sustainability": sustainability,
            }

            current_soc = target_soc

        expensive_hours = [h for h, e in plan.items() if e["action"].startswith("Ontladen")]
        if expensive_hours:
            min_expensive_hour = min(expensive_hours)
            for h, entry in plan.items():
                if h < min_expensive_hour and entry["action"] in ("Vasthouden", "Vasthouden (zon morgen verwacht)"):
                    if entry["target_soc"] < max_soc - 10:
                        plan[h]["target_soc"] = min(max_soc, entry["target_soc"] + 10.0)
                        plan[h]["action"] = "Laden (voor piekuur)"
                        plan[h]["reason"] += f" | Duur uur verwacht om {min_expensive_hour}:00"

        return plan

    def _estimated_savings_24h(self, plan: dict) -> float:
        total = 0.0
        cap_wh = self._cap_wh
        for entry in plan.values():
            action = entry.get("action", "")
            price = entry.get("price_eur", 0.0)
            if "Ontladen" in action and price > 0:
                discharge_kwh = (cap_wh * 0.20 / 1000) * (self._plan_step_hours or 1.0)
                total += discharge_kwh * price
        return round(total, 4)

    def _evaluate_forecast_learning(self, now_local, actual_load_kw):
        """Vergelijkt de voorspelling van een uur geleden met de werkelijkheid nu."""
        key = (now_local - timedelta(hours=1)).strftime("%Y-%m-%d-%H")
        actual_pv_w = self.data.get("solar_to_bat", 0.0) + self.data.get("solar_to_grid", 0.0)
        actual_load_w = actual_load_kw * 1000
        did_eval = forecast_learning.evaluate_hour(self._forecast_learning, key, actual_pv_w, actual_load_w)
        if did_eval:
            self.data["forecast_leren_samenvatting"] = forecast_learning.summary_text(self._forecast_learning)
            self.data["forecast_leren_pv_nauwkeurigheid"] = forecast_learning.accuracy_pct(
                self._forecast_learning.pv_last_error_pct, self._forecast_learning.pv_samples)
            self.data["forecast_leren_verbruik_nauwkeurigheid"] = forecast_learning.accuracy_pct(
                self._forecast_learning.load_last_error_pct, self._forecast_learning.load_samples)

    async def _build_plan_dp(self, now_local, price_forecast, profile_weight=1.0):
        if self._dp_building:
            _LOGGER.debug("BatteryLabs: DP-optimizer nog bezig, sla deze rebuild over")
            return

        pv_hourly = self._get_pv_hourly_forecast()
        self.data["_pv_hourly"] = pv_hourly
        self.data["pv_forecast_today_kwh"] = round(sum(pv_hourly) / 1000, 2)

        prices_eur = [e.get("price_eur", self.data["_price_now"]) for e in price_forecast]
        n_hours = len(prices_eur)
        if n_hours == 0:
            self._set_plan({})
            return
        step_hours = _detect_step_hours(price_forecast)
        self._plan_step_hours = step_hours

        # Begrens het aantal DP-stappen ongeacht de brondata-resolutie of
        # -horizon, zodat de rekentijd (en dus de executor-thread) altijd
        # begrensd blijft -- ongeacht of de prijssensor uur- of kwartierdata
        # levert, of een horizon van 1 dag of 5 dagen aanlevert.
        if n_hours > MAX_DP_PLAN_STEPS:
            price_forecast = price_forecast[:MAX_DP_PLAN_STEPS]
            prices_eur = prices_eur[:MAX_DP_PLAN_STEPS]
            n_hours = MAX_DP_PLAN_STEPS

        day_of_week = now_local.weekday()
        all_profile_vals = [v * 1000 for row in self._profile for v in row if v > 0]
        conservative_w = (sum(all_profile_vals) / len(all_profile_vals)
                          if all_profile_vals else 400.0)
        house_load_kwh = []
        pv_surplus_kwh = []
        sustainability = []
        for i, entry in enumerate(price_forecast[:n_hours]):
            hour = entry["hour"].astimezone().hour if hasattr(entry.get("hour"), "astimezone") else (now_local.hour + i) % 24
            profiel_w = self._profile[day_of_week][hour] * 1000
            if profiel_w < 1.0:
                profiel_w = conservative_w * 1.2 if 7 <= hour < 22 else conservative_w * 0.6
            mixed_w = profile_weight * profiel_w + (1 - profile_weight) * (
                conservative_w * 1.2 if 7 <= hour < 22 else conservative_w * 0.6
            )
            pv_w = forecast_learning.apply_pv_correction(self._forecast_learning, hour, pv_hourly[hour] if hour < len(pv_hourly) else 0.0)
            mixed_w = forecast_learning.apply_load_correction(self._forecast_learning, hour, mixed_w)
            net_w = max(0.0, mixed_w - pv_w)
            house_load_kwh.append((net_w / 1000.0) * step_hours)
            pv_surplus_kwh.append((max(0.0, pv_w - mixed_w) / 1000.0) * step_hours)
            sustainability.append(entry.get("sustainability", 0))
            if i == 0:
                forecast_learning.record_prediction(self._forecast_learning, now_local.strftime("%Y-%m-%d-%H"), pv_w, mixed_w)

        ps_min_soc = float(self.data.get("peak_shaving_min_soc", 15.0))
        min_soc = self._config.get("min_soc", 10.0)
        cap_kwh = self._cap_wh / 1000.0
        bat_rte = self._bat_profile.rte
        eta = bat_rte ** 0.5

        # Economische slijtagekost i.p.v. een hard cyclusbudget -- zie
        # dp_optimizer.solve() voor de onderbouwing.
        bat_cost_per_module = {"US2000C": 800.0, "US3000C": 1100.0, "US5000": 1600.0}
        battery_replacement_eur = bat_cost_per_module.get(self._bat_profile.model, 1200.0) * self._modules
        wear_coeff_eur = self._bat_profile.degradation_per_cycle(1.0) * battery_replacement_eur
        feed_in_price = self._get_feed_in_price()
        self._dp_building = True
        t_start = time.monotonic()
        try:
            import functools
            solve_fn = functools.partial(
                dp_optimizer.solve,
                prices_eur=prices_eur,
                house_load_kwh=house_load_kwh,
                sustainability=sustainability,
                start_soc=self.data["soc"],
                cap_kwh=cap_kwh,
                eta=eta,
                max_power_kw=self._inv_profile.power_cont_25c_w * 3 / 1000.0,
                min_soc=max(min_soc, ps_min_soc),
                max_soc=95.0,
                wear_coeff_eur=wear_coeff_eur,
                pv_surplus_kwh=pv_surplus_kwh,
                feed_in_price_eur=feed_in_price,
                sustainability_weight=0.05,
                step_hours=step_hours,
            )
            future = self.hass.async_add_executor_job(solve_fn)
            future.add_done_callback(self._on_dp_solve_done)
            try:
                results, expected_cost = await asyncio.wait_for(asyncio.shield(future), timeout=45.0)
            except asyncio.TimeoutError:
                _LOGGER.warning(
                    "BatteryLabs: DP-optimizer duurt langer dan 45s (%d stappen van %.2fu), "
                    "val terug op greedy plan voor deze cyclus -- vorige berekening loopt op de "
                    "achtergrond door en meldt zichzelf klaar",
                    n_hours, step_hours,
                )
                self._set_plan(self._build_plan(now_local, [0.0, 0.0, 0.0], price_forecast, profile_weight))
                return
        except Exception as exc:
            self._dp_building = False
            _LOGGER.warning("BatteryLabs: DP-optimizer faalde (%s), val terug op greedy plan", exc)
            self._set_plan(self._build_plan(now_local, [0.0, 0.0, 0.0], price_forecast, profile_weight))
            return

        _LOGGER.info(
            "BatteryLabs: DP-optimizer klaar in %.2fs (%d stappen van %.2fu elk)",
            time.monotonic() - t_start, n_hours, step_hours,
        )
        self.data["dp_expected_cost_eur"] = round(expected_cost, 4)
        plan = {}
        for r in results:
            slot_start = price_forecast[r.hour_offset]["hour"] if r.hour_offset < len(price_forecast) else r.hour_offset
            action = "Ontladen (DP-optimaal)" if r.action_kwh < -0.05 else (
                "Laden (DP-optimaal)" if r.action_kwh > 0.05 else "Vasthouden (DP-optimaal)")
            plan[slot_start] = {
                "target_soc": r.target_soc, "action": action,
                "reason": f"DP-planning: {r.action_kwh:+.1f} kWh bij €{r.price_eur:.4f}/kWh (incl. slijtagekost, stap {step_hours*60:.0f} min)",
                "price_eur": round(r.price_eur, 5), "sustainability": r.sustainability_score,
            }
        self._set_plan(plan)

    def _on_dp_solve_done(self, _future) -> None:
        """Wordt aangeroepen zodra de (mogelijk verlaten) executor-thread echt
        klaar is. Pas dan mag een volgende DP-rebuild starten -- anders zou
        een trage berekening (die wait_for al liet verlopen) alsnog naast een
        nieuwe kunnen blijven draaien en de executor-pool uitputten."""
        self._dp_building = False

    def _set_plan(self, plan: dict) -> None:
        """Slaat het plan op en bouwt een gesorteerde sleutel-index zodat
        _plan_entry_at() met bisect kan zoeken (O(log n)) i.p.v. een lineaire
        scan (O(n)) -- essentieel nu kwartier-data het plan 4-5x groter maakt."""
        self._plan = plan
        self._plan_keys_sorted = sorted(
            k for k in plan.keys() if hasattr(k, "tzinfo")
        )

    def _plan_entry_at(self, dt_utc: datetime) -> dict:
        step = timedelta(hours=self._plan_step_hours or 1.0)
        if self._plan_keys_sorted:
            idx = bisect.bisect_right(self._plan_keys_sorted, dt_utc) - 1
            if 0 <= idx < len(self._plan_keys_sorted):
                ts = self._plan_keys_sorted[idx]
                if ts <= dt_utc < ts + step:
                    return self._plan.get(ts, {})
        if not self._plan:
            return {}
        return self._plan.get(dt_utc.astimezone().hour, {})

    async def handle_p1_update(self, event=None):
        now = datetime.now()
        now_local = now.astimezone()
        dt = (now - self._last_run).total_seconds()
        self._last_run = now
        if dt <= 0:
            return
        dt = min(dt, 5.0)

        p_net_phases = []
        for i in range(1, 4):
            imp = self._safe_state(self._config.get(f"l{i}_import_kw", "")) * 1000
            exp = self._safe_state(self._config.get(f"l{i}_export_kw", "")) * 1000
            p_net_phases.append(imp - exp)

        p_net_real = sum(p_net_phases)
        self.data["p_net_real"] = p_net_real

        zonneplan_id = self._config.get("zonneplan_sensor", "")
        price = self._safe_state(zonneplan_id, fallback=0.0)
        if price > 10.0:
            price = price / ZONNEPLAN_PRICE_DIVISOR
        self.data["_price_now"] = price
        t_out = self._safe_state(self._config.get("temp_sensor", ""), fallback=20.0)

        t_bat = self.data["t_bat"]
        temp_factor = self._bat_profile.capacity_factor_at_temp(t_bat)
        cap_wh_effective = self._cap_wh * temp_factor
        max_charge_w = self._bat_profile.max_charge_power_w(self._modules, t_bat)
        max_discharge_w = self._bat_profile.max_discharge_power_w(self._modules, t_bat)
        inv_max_per_phase = self._inv_profile.power_at_temp(
            max(self.data["t_inv1"], self.data["t_inv2"], self.data["t_inv3"])
        )

        p_bat_phases = [0.0, 0.0, 0.0]
        soc = self.data["soc"]
        min_soc = self._config.get("min_soc", 10.0)
        SOC_CHARGE_MAX = 99.9
        mode = self.data["mode"]

        ps_threshold_w = float(self.data.get("peak_shaving_threshold_w", 2200.0))
        ps_min_soc     = float(self.data.get("peak_shaving_min_soc", 15.0))

        if mode == MODE_FORCE:
            if soc < SOC_CHARGE_MAX:
                charge_per_phase = min(inv_max_per_phase, max_charge_w / 3)
                p_bat_phases = [charge_per_phase] * 3

        elif mode == MODE_AUTO:
            ps_active_this_cycle = False

            house_reserve_soc = self.data.get("_house_reserve_soc", min_soc + 10.0)

            plan_action_now = self.data.get("plan_action", "")
            if price < PRICE_NEGATIVE_THRESHOLD:
                tariff_cls = "negative"
            elif "Laden" in plan_action_now:
                tariff_cls = "cheap"
            elif "Ontladen" in plan_action_now:
                tariff_cls = "expensive"
            else:
                tariff_cls = "normal"

            plan_is_hold = "Vasthouden" in plan_action_now

            for i in range(3):
                p_phase = p_net_phases[i]

                if price < PRICE_NEGATIVE_THRESHOLD:
                    if soc < SOC_CHARGE_MAX:
                        p_bat_phases[i] = min(inv_max_per_phase, max_charge_w / 3)
                    continue

                if p_phase < -100.0 and soc < SOC_CHARGE_MAX:
                    p_bat_phases[i] = min(abs(p_phase), inv_max_per_phase,
                                          max_charge_w / 3)
                    continue

                # Zolang het DP-plan "Vasthouden" adviseert, mag eigenverbruik/PS de
                # batterij alleen ontladen tot de systeem-berekende huisreserve --
                # daaronder beschermt het plan iets specifieks (dure periode, PV-tekort)
                # dat niet zomaar overruled moet worden door een klein beetje huisverbruik.
                ps_floor = max(ps_min_soc + 2.0, house_reserve_soc) if plan_is_hold else ps_min_soc + 2.0
                ps_soc_ok = (soc > ps_floor) or (self._ps_active and soc > ps_floor - 1.5)
                if p_phase > POWER_ACTIVE_THRESHOLD_W and ps_soc_ok:
                    ps_deliver = min(p_phase, ps_threshold_w,
                                     inv_max_per_phase, max_discharge_w / 3)
                    p_bat_phases[i] = -ps_deliver
                    if ps_deliver > POWER_ACTIVE_THRESHOLD_W:
                        ps_active_this_cycle = True

                elif tariff_cls == "cheap" and soc < SOC_CHARGE_MAX:
                    if not any(p_net_phases[j] > ps_threshold_w
                               for j in range(3) if j != i):
                        p_bat_phases[i] = min(
                            inv_max_per_phase * 0.60,
                            max_charge_w / 3,
                        )

                elif tariff_cls == "normal" and soc < house_reserve_soc and soc < SOC_CHARGE_MAX:
                    p_bat_phases[i] = min(
                        inv_max_per_phase * 0.25,
                        max_charge_w / 3,
                    )

                elif tariff_cls == "expensive" and soc > house_reserve_soc + 5.0 and self.data.get("_arbitrage_depth_pct", 0) > 0:
                    extra_sell = max(0.0, soc - house_reserve_soc - 5.0)
                    sell_scale = min(1.0, extra_sell / 20.0)
                    sell_w = min(
                        inv_max_per_phase * 0.70 * (self.data.get("_arbitrage_depth_pct", 0) / 25.0) * sell_scale,
                        max_discharge_w / 3,
                    )
                    if sell_w > POWER_ACTIVE_THRESHOLD_W:
                        p_bat_phases[i] = -sell_w
                        ps_active_this_cycle = True

                elif soc < ps_min_soc + 2.0 and soc < SOC_CHARGE_MAX:
                    if not any(p_net_phases[j] > ps_threshold_w
                               for j in range(3) if j != i):
                        p_bat_phases[i] = min(
                            inv_max_per_phase * 0.20,
                            max_charge_w / 3,
                        )

            self.data["peak_shaving_actief"] = ps_active_this_cycle

        else:
            ps_active_this_cycle = False
            ps_soc_ok = (soc > ps_min_soc + 2.0) or (self._ps_active and soc > ps_min_soc + 0.5)
            for i in range(3):
                p_phase = p_net_phases[i]
                if p_phase > POWER_ACTIVE_THRESHOLD_W and ps_soc_ok:
                    ps_deliver = min(p_phase, ps_threshold_w,
                                     inv_max_per_phase, max_discharge_w / 3)
                    p_bat_phases[i] = -ps_deliver
                    if ps_deliver > POWER_ACTIVE_THRESHOLD_W:
                        ps_active_this_cycle = True
                elif p_phase < -POWER_ACTIVE_THRESHOLD_W and soc < SOC_CHARGE_MAX:
                    p_bat_phases[i] = min(abs(p_phase), inv_max_per_phase,
                                           max_charge_w / 3)
            self.data["peak_shaving_actief"] = ps_active_this_cycle
        self._ps_active = ps_active_this_cycle

        p_total_raw = sum(p_bat_phases)
        eff = self._inv_profile.efficiency_at_load(abs(p_total_raw))
        p_eff = p_total_raw * eff if eff > 0 else 0.0

        self.data.update({
            "p1": p_bat_phases[0], "p2": p_bat_phases[1], "p3": p_bat_phases[2],
            "p_total": p_total_raw,
        })

        for i in range(1, 4):
            val = self.data[f"p{i}"]
            sk = f"inv_l{i}_stat"
            self.data[sk] = (
                "Standby" if abs(val) < POWER_ACTIVE_THRESHOLD_W
                else "Laden" if val > 0
                else "Ontladen"
            )

        bat_rte    = self._bat_profile.rte
        p_loss_bat = (1.0 - bat_rte) * abs(p_total_raw)
        t_bat_ss   = t_out + 0.008 * p_loss_bat
        if self._t_bat_internal == 20.0 and self.data["t_bat"] != 20.0:
            self._t_bat_internal = self.data["t_bat"]
        self._t_bat_internal += (dt / 800.0) * (t_bat_ss - self._t_bat_internal)
        self._t_bat_internal = max(
            self._bat_profile.temp_discharge_min_c,
            min(self._t_bat_internal, self._bat_profile.temp_discharge_max_c)
        )
        self.data["t_bat"] = round(self._t_bat_internal, 1)

        R_th_inv  = 0.015
        tau_inv   = 300.0
        inv_max_t = self._inv_profile.temp_operating_max_c
        for i, pk in enumerate(["p1", "p2", "p3"], start=1):
            p_inv  = abs(self.data[pk])
            t_key  = f"t_inv{i}"
            t_ss   = t_out + R_th_inv * p_inv
            if self._t_inv_internal[i-1] == 25.0 and self.data[t_key] != 25.0:
                self._t_inv_internal[i-1] = self.data[t_key]
            self._t_inv_internal[i-1] += (dt / tau_inv) * (t_ss - self._t_inv_internal[i-1])
            self._t_inv_internal[i-1] = max(
                t_out - 5.0,
                min(self._t_inv_internal[i-1], inv_max_t)
            )
            self.data[t_key] = round(self._t_inv_internal[i-1], 1)

        t_bat = self.data["t_bat"]
        if t_bat > TEMP_BAT_WARNING_HIGH:
            health = "Warning: Overheating"
        elif t_bat < TEMP_BAT_CAUTION_LOW:
            health = "Caution: Low Temp"
        elif soc < min_soc + 2:
            health = "Caution: Low Battery"
        elif self.data["soh"] < SOH_WARNING_THRESHOLD:
            health = "Warning: High Degradation"
        elif t_bat < self._bat_profile.temp_charge_min_c:
            health = "Caution: Charging blocked (temp)"
        else:
            health = "Healthy"
        self.data["health_msg"] = health

        if p_net_real < 0:
            overschot = abs(p_net_real)
            self.data["solar_to_bat"] = min(overschot, max(0.0, p_total_raw))
            self.data["solar_to_grid"] = max(0.0, overschot - self.data["solar_to_bat"])
        else:
            self.data["solar_to_bat"] = 0.0
            self.data["solar_to_grid"] = 0.0

        if p_total_raw < -50:
            usable_wh = ((soc - min_soc) / 100) * cap_wh_effective
            self.data["time_to_empty"] = self._format_time(usable_wh / abs(p_total_raw))
            self.data["time_to_full"] = "N.v.t."
        elif p_total_raw > 50:
            needed_wh = ((100 - soc) / 100) * cap_wh_effective
            self.data["time_to_full"] = self._format_time(needed_wh / p_total_raw)
            self.data["time_to_empty"] = "N.v.t."
        else:
            self.data["time_to_empty"] = "N.v.t."
            self.data["time_to_full"] = "N.v.t."

        if p_total_raw > 0:
            self.data["energy_in"] += (p_eff / 1000) * (dt / 3600)
        elif p_total_raw < -POWER_ACTIVE_THRESHOLD_W:
            energy_out_delta = (abs(p_eff) / 1000) * (dt / 3600)
            self.data["energy_out"] += energy_out_delta
            if self._cap_kwh > 0:
                dod_this_step = energy_out_delta / self._cap_kwh
                self.data["cycles"] = round(
                    self.data.get("cycles", 0.0) + dod_this_step, 4
                )
                soh_loss = self._bat_profile.degradation_per_cycle(dod_this_step)
                self.data["soh"] = max(0.0, self.data["soh"] - soh_loss * 100)
                self.data["_soh_loss_today"] = self.data.get("_soh_loss_today", 0.0) + soh_loss * 100

        if self.data["energy_in"] > 0.01:
            raw_rte = (self.data["energy_out"] / self.data["energy_in"]) * 100
            self.data["rte"] = round(min(raw_rte, 99.0), 1)

        new_soc = soc + (p_eff * (dt / 3600) / cap_wh_effective) * 100
        self.data["soc"] = max(0.0, min(100.0, new_soc))

        self.data["sim_p_total"] = p_net_real + p_total_raw
        self.data["sim_p1"] = p_net_phases[0] + p_bat_phases[0]
        self.data["sim_p2"] = p_net_phases[1] + p_bat_phases[1]
        self.data["sim_p3"] = p_net_phases[2] + p_bat_phases[2]

        self.data["v_dc"] = self._bat_profile.voltage_at_soc(self.data["soc"] / 100)
        v_dc_safe = max(self.data["v_dc"], DC_VOLTAGE_MIN)
        self.data["i_dc"] = self.data["p_total"] / v_dc_safe

        self.data["status"] = (
            "Laden" if p_total_raw > 50
            else "Ontladen" if p_total_raw < -50
            else "Standby"
        )

        _house_res = self.data.get("_house_reserve_soc", min_soc + 10.0)
        self._update_actie_uitleg(p_total_raw, p_net_phases, price, soc,
                                   ps_min_soc, min_soc, _house_res)

        if (now - self._last_save).total_seconds() >= SAVE_INTERVAL_S:
            self._last_save = now
            await self._async_save_data()

        for cb in self._listeners:
            try:
                cb()
            except Exception:
                pass

    def _update_actie_uitleg(self, p_total_raw, p_net_phases, price,
                              soc, ps_min_soc, min_soc, house_reserve_soc):
        p_net_total = sum(p_net_phases)
        p_bat = p_total_raw
        mode  = self.data["mode"]

        uitleg = ""
        reden  = ""
        if abs(p_bat) < POWER_ACTIVE_THRESHOLD_W:
            if soc <= ps_min_soc + 0.2:
                uitleg  = f"⏸ Batterij in rust — SoC {soc:.0f}% op minimum ({ps_min_soc:.0f}%)"
                reden   = "Batterij beschermt zichzelf. Zodra SoC stijgt boven minimum herstart de sturing."
            elif soc >= 99.0:
                uitleg  = "⏸ Batterij vol — wacht op verbruik of gunstig verkoopmoment"
                reden   = f"SoC {soc:.0f}% — volledig opgeladen."
            elif abs(p_net_total) < POWER_ACTIVE_THRESHOLD_W:
                uitleg  = "⏸ Standby — huis in balans, geen actie nodig"
                reden   = f"Geen netto import of export. SoC {soc:.0f}%, prijs €{price:.4f}/kWh."
            else:
                uitleg  = "⏸ Standby"
                reden   = f"SoC {soc:.0f}%"

        elif p_bat > POWER_ACTIVE_THRESHOLD_W:
            kw = p_bat / 1000

            if price < PRICE_NEGATIVE_THRESHOLD:
                uitleg = f"⚡ Laden {kw:.1f} kW — prijs NEGATIEF, net betaalt voor afname"
                reden  = f"Stroomprijs €{price:.4f}/kWh. Maximaal laden is nu voordelig."

            elif p_net_total < -100:
                pv_kw = abs(p_net_total) / 1000
                uitleg = f"☀️ Laden {kw:.1f} kW — PV overschot {pv_kw:.1f} kW vanuit zon"
                reden  = f"Zonne-energie die anders teruggeleverd zou worden, wordt opgeslagen. Prijs €{price:.4f}/kWh."

            elif soc < ps_min_soc + 2.0:
                uitleg = f"🔋 Noodlading {kw:.1f} kW — SoC {soc:.0f}% te laag voor eigenverbruik"
                reden  = (f"Batterij moet boven {ps_min_soc:.0f}% SoC komen om eigenverbruik te kunnen dekken. "
                          f"Laden op laag vermogen.")

            else:
                plan_actie = self.data.get("plan_action", "")
                if "goedkoop" in plan_actie.lower() or "dal" in plan_actie.lower():
                    uitleg = f"💰 Laden {kw:.1f} kW — goedkoop tarief, laden voor duurder uur"
                    reden  = f"Prijs nu €{price:.4f}/kWh (laag tarief). Opslaan voor hogere prijsperiode."
                elif "piekuur" in plan_actie.lower():
                    uitleg = f"💰 Laden {kw:.1f} kW — opladen vóór piekuur"
                    reden  = f"Prijs nu €{price:.4f}/kWh. Batterij wordt geladen vóór duurder uur."
                else:
                    uitleg = f"🔋 Laden {kw:.1f} kW — tarief €{price:.4f}/kWh"
                    reden  = f"SoC {soc:.0f}% → doel {self.data.get('plan_soc_target', soc):.0f}%."

        else:
            kw = abs(p_bat) / 1000
            huis_kw = max(0.0, p_net_total) / 1000
            ps_actief = self.data.get("peak_shaving_actief", False)

            if ps_actief and huis_kw > 0.05:
                bespaard = huis_kw * price
                if soc > house_reserve_soc + 5.0:
                    uitleg = (f"🏠+💸 Eigenverbruik {huis_kw:.1f} kW gedekt + verkoop "
                              f"— SoC {soc:.0f}% boven reserve {house_reserve_soc:.0f}%")
                    reden  = (f"Batterij dekt huis ({huis_kw:.1f} kW, €{bespaard:.4f}/uur bespaard) "
                              f"én verkoopt overschot. Prijs €{price:.4f}/kWh.")
                else:
                    uitleg = f"🏠 Eigenverbruik — {huis_kw:.1f} kW huis gedekt, net op 0W"
                    reden  = (f"Batterij levert {kw:.1f} kW aan huis (piekdrempel {self.data.get('peak_shaving_threshold_w',2200)/1000:.1f} kW/fase). "
                              f"Netimport vermeden. Prijs €{price:.4f}/kWh → besparing ~€{bespaard:.4f}/uur.")

            elif soc > house_reserve_soc + 5.0:
                plan_actie = self.data.get("plan_action", "")
                uitleg = (f"💸 Ontladen {kw:.1f} kW — duur uur, SoC {soc:.0f}% boven "
                          f"reserve {house_reserve_soc:.0f}%")
                reden  = (f"Prijs €{price:.4f}/kWh (hoog tarief). Batterij verkoopt opgeslagen energie. "
                          f"Stopt bij SoC {self.data.get('plan_soc_target', min_soc):.0f}%.")

            else:
                uitleg = f"🏠 Eigenverbruik — {kw:.1f} kW huis gedekt"
                reden  = (f"Batterij dekt huis verbruik. SoC {soc:.0f}%, "
                          f"reserve nodig {house_reserve_soc:.0f}%.")

        self.data["actie_uitleg"] = uitleg
        self.data["actie_reden"]  = reden

    async def update_slow(self, _=None):
        now = datetime.now()
        now_local = now.astimezone()
        dt_slow = min(120.0, max(30.0, (now - self._last_slow_run).total_seconds()))
        self._last_slow_run = now

        t_out = self._safe_state(self._config.get("temp_sensor", ""), fallback=20.0)
        p_net_phases = []
        for i in range(1, 4):
            imp = self._safe_state(self._config.get(f"l{i}_import_kw", "")) * 1000
            exp = self._safe_state(self._config.get(f"l{i}_export_kw", "")) * 1000
            p_net_phases.append(imp - exp)

        await self._refresh_solar_forecast(now_local)
        self.data["_pv_hourly"] = self._get_pv_hourly_forecast()
        self.data["pv_forecast_today_kwh"] = round(sum(self.data["_pv_hourly"]) / 1000, 3)

        p_bat_contribution = max(0.0, -self.data["p_total"])
        p_gross_consumption_kw = (sum(p_net_phases) + p_bat_contribution) / 1000
        if p_gross_consumption_kw > 0:
            day = now_local.weekday()
            hour = now_local.hour
            old = self._profile[day][hour]
            self._profile[day][hour] = (
                PROFILE_EMA_ALPHA * p_gross_consumption_kw
                + (1 - PROFILE_EMA_ALPHA) * old
            )
            slot_days = self._profile_days[day][hour]
            slot_days.add(now_local.date().isoformat())
            if len(slot_days) > PROFILE_DAYS_CAP:
                self._profile_days[day][hour] = set(sorted(slot_days)[-PROFILE_DAYS_CAP:])

        self._update_profile_progress()
        self._evaluate_forecast_learning(now_local, p_gross_consumption_kw)
        if now_local.hour != self._last_forecast_record_hour:
            self._last_forecast_record_hour = now_local.hour
            day_rec = now_local.weekday()
            hour_rec = now_local.hour
            profiel_w_rec = self._profile[day_rec][hour_rec] * 1000
            if profiel_w_rec < 1.0:
                all_vals_rec = [v * 1000 for row in self._profile for v in row if v > 0]
                profiel_w_rec = (sum(all_vals_rec) / len(all_vals_rec)) if all_vals_rec else 350.0
            pv_hourly_rec = self.data.get("_pv_hourly", [0.0] * 24)
            pv_w_rec = pv_hourly_rec[hour_rec] if hour_rec < len(pv_hourly_rec) else 0.0
            forecast_learning.record_prediction(
                self._forecast_learning,
                now_local.strftime("%Y-%m-%d-%H"),
                pv_w_rec,
                profiel_w_rec,
            )

        try:
            install_dt = datetime.strptime(self.data.get("install_date", ""), "%Y-%m-%d")
            active_days = max(0.0, (now - install_dt).total_seconds() / 86400)
        except Exception:
            active_days = 0.0
        self.data["_advisor_days"] = round(active_days, 2)

        profile_weight = 0.0
        if active_days >= 14:
            profile_weight = 1.0
        elif active_days >= 7:
            profile_weight = (active_days - 7) / 7

        pv_hourly = self.data.get("_pv_hourly", [0.0] * 24)
        forecast_slow = self.data.get("_price_forecast", [])

        all_profile_vals = [v * 1000 for row in self._profile for v in row if v > 0]
        conservative_w = (sum(all_profile_vals) / len(all_profile_vals)
                          if all_profile_vals else 350.0)

        hours_to_cheap = 8
        p_cheap_thr_slow = None
        if forecast_slow:
            prices_slow = [e.get("price_eur", 0) for e in forecast_slow]
            ps = sorted(prices_slow)
            n = len(ps)
            p_cheap_thr_slow = ps[max(0, int(n * PRICE_PERCENTILE_CHEAP / 100) - 1)]
            for offset in range(1, 13):
                h = (now_local.hour + offset) % 24
                entry = next(
                    (e for e in forecast_slow
                     if e.get("hour") and hasattr(e["hour"], "astimezone")
                     and e["hour"].astimezone().hour == h),
                    None
                )
                if entry and entry.get("price_eur", 999) <= p_cheap_thr_slow:
                    hours_to_cheap = offset
                    break

        expected_net_wh = 0.0
        day_of_week_slow = now_local.weekday()
        for offset in range(1, hours_to_cheap + 1):
            h = (now_local.hour + offset) % 24
            profiel_w = self._profile[day_of_week_slow][h] * 1000
            if profiel_w < 1.0:
                profiel_w = conservative_w
            pv_w = pv_hourly[h] if h < len(pv_hourly) else 0.0
            net_w = max(0.0, profiel_w - pv_w)
            expected_net_wh += net_w

        min_soc_conf = float(self._config.get("min_soc", 10.0))
        house_reserve_raw = min(
            50.0,
            (expected_net_wh / max(self._cap_wh, 1)) * 100 + min_soc_conf + 5.0
        )
        ps_min_soc_conf = float(self.data.get("peak_shaving_min_soc", 15.0))
        min_soc_hard = float(self._config.get("min_soc", 10.0))
        house_reserve = max(house_reserve_raw, ps_min_soc_conf, min_soc_hard)
        self.data["_house_reserve_soc"] = round(house_reserve, 1)

        day_of_week_load = now_local.weekday()
        load_forecast_w = []
        for offset_load in range(24):
            hour_load = (now_local.hour + offset_load) % 24
            profiel_w_load = self._profile[day_of_week_load][hour_load] * 1000
            if profiel_w_load < 1.0:
                profiel_w_load = conservative_w * 1.2 if 7 <= hour_load < 22 else conservative_w * 0.6
            load_forecast_w.append(round(profiel_w_load, 1))
        self.data["verbruik_forecast_w"] = load_forecast_w

        mode = self.data["mode"]
        if mode == MODE_AUTO:
            price_forecast = self._parse_price_forecast()
            self.data["_price_forecast"] = price_forecast
            spread_prices = [e.get("price_eur", 0) for e in price_forecast] if price_forecast else [price]
            day_spread_now = (max(spread_prices) - min(spread_prices)) if spread_prices else 0.0
            spread_scale_now = 0.0
            if day_spread_now > PRICE_SPREAD_MIN_EUR:
                spread_scale_now = min(1.0, (day_spread_now - PRICE_SPREAD_MIN_EUR) / (PRICE_SPREAD_MAX_EUR - PRICE_SPREAD_MIN_EUR))
            self.data["_arbitrage_depth_pct"] = spread_scale_now * PRICE_SPREAD_MAX_DEPTH_PCT
            self.data["day_spread_eur"] = round(day_spread_now, 4)
            self.data["arbitrage_actief"] = spread_scale_now > 0.0

            now_utc_check = now_local.astimezone(timezone.utc)
            plan_needs_rebuild = not self._plan or not self._plan_entry_at(now_utc_check)
            if plan_needs_rebuild and self.data.get("use_dp_optimizer", True) and not self._dp_building:
                await self._build_plan_dp(now_local, price_forecast, profile_weight=profile_weight)
                self._last_plan_hour = now_local.hour
                self.data["_plan_full"] = self._plan
                self.data["plan_savings_24h"] = self._estimated_savings_24h(self._plan)
            if plan_needs_rebuild and not self.data.get("use_dp_optimizer", True):
                self._set_plan(self._build_plan(
                    now_local, p_net_phases, price_forecast,
                    profile_weight=profile_weight,
                ))
                self._last_plan_hour = now_local.hour
                self.data["_plan_full"] = self._plan
                self.data["plan_savings_24h"] = self._estimated_savings_24h(self._plan)
            current_plan = self._plan_entry_at(now_utc_check)
            next_plan = self._plan_entry_at(now_utc_check + timedelta(hours=self._plan_step_hours or 1.0))

            base_action = current_plan.get("action", "N.v.t.")
            self.data["plan_soc_target"] = current_plan.get("target_soc", self.data["soc"])
            self.data["plan_next_action"] = next_plan.get("action", "N.v.t.")

            if base_action in ("Vasthouden", "N.v.t.") and self.data.get("peak_shaving_actief"):
                self.data["plan_action"] = f"{base_action} (PS actief)"
            elif "Vasthouden" in base_action and self.data.get("peak_shaving_actief"):
                # Dekt ook DP-optimizer teksten als "Vasthouden (DP-optimaal)" en
                # greedy-planner varianten als "Vasthouden (spread te klein)".
                self.data["plan_action"] = f"{base_action} + Eigenverbruik/PS actief"
            else:
                self.data["plan_action"] = base_action

            if not current_plan:
                layer = (
                    "Laag 3 (volledig)" if active_days >= 14 else
                    f"Laag 2 ({profile_weight*100:.0f}% profiel)" if active_days >= 7 else
                    "Laag 1 (prijsarbitrage)"
                )
                self.data["plan_action"] = f"Plan bouwen... [{layer}]"

        zonneplan_id = self._config.get("zonneplan_sensor", "")
        price = self._safe_state(zonneplan_id, fallback=0.0)
        if price > 10.0:
            price = price / ZONNEPLAN_PRICE_DIVISOR
        fixed_price = float(self._config.get("fixed_price_eur", 0.25))
        effective_price = price if price > 0.01 else fixed_price

        if effective_price > 0:
            p_total_raw = self.data["p_total"]
            eff_slow = self._inv_profile.efficiency_at_load(abs(p_total_raw)) if p_total_raw != 0 else 1.0
            p_ac_discharge = abs(p_total_raw) * eff_slow if p_total_raw < 0 else 0.0
            if p_total_raw < -POWER_ACTIVE_THRESHOLD_W:
                self.data["savings"] += (p_ac_discharge / 1000) * (dt_slow / 3600) * effective_price
            if self.data["solar_to_grid"] > POWER_ACTIVE_THRESHOLD_W:
                self.data["savings"] += (self.data["solar_to_grid"] / 1000) * (dt_slow / 3600) * effective_price

        system_cost = self._config.get("system_cost_euro", 15000.0)
        self.data["roi_perc"] = (
            (self.data["savings"] / system_cost) * 100 if system_cost > 0 else 0.0
        )

        active_min_soc = float(self._config.get("min_soc", 10.0))
        restcap = max(0.0, (self.data["soc"] - active_min_soc) / 100 * self._usable_kwh)
        self.data["restcapaciteit_kwh"] = round(restcap, 3)

        days_active = max(1.0, active_days)
        self.data["savings_per_year"] = round(
            (self.data["savings"] / days_active) * 365, 2
        )

        p_net_real = sum(p_net_phases)
        p_bat = self.data["p_total"]
        p_discharge = max(0.0, -p_bat)
        p_import = max(0.0, p_net_real)
        gross_consumption = max(0.001, p_import + p_discharge) / 1000
        s_bat = max(0.0, self.data.get("solar_to_bat", 0.0))
        s_grid = max(0.0, self.data.get("solar_to_grid", 0.0))
        solar_generated = (s_bat + s_grid) / 1000
        if solar_generated > 0.001:
            self.data["self_consumption"] = round(
                min(100.0, (s_bat / max(s_bat + s_grid, 0.001)) * 100), 1
            )
        if gross_consumption > 0:
            self.data["autarky"] = round(
                min(100.0, (solar_generated / gross_consumption) * 100), 1
            )

        self._score_engine.update(self.data, self._config)
        se  = self._score_engine
        sub = se.sub_scores()
        self.data["score_totaal"]      = se.total_score
        self.data["score_klasse"]      = se.score_class
        self.data["score_capaciteit"]  = sub["capaciteit"]
        self.data["score_omvormer"]    = sub["omvormer"]
        self.data["score_rte"]         = sub["rte"]
        self.data["score_financieel"]  = sub["financieel"]
        self.data["score_gezondheid"]  = sub["gezondheid"]
        self.data["score_ev"]          = sub["ev"]
        self.data["advies_capaciteit"] = se.advice_confirmed["capaciteit"]
        self.data["advies_omvormer"]   = se.advice_confirmed["omvormer"]
        self.data["advies_rte"]        = se.advice_confirmed["rte"]
        self.data["advies_financieel"] = se.advice_confirmed["financieel"]
        self.data["advies_gezondheid"] = se.advice_confirmed["gezondheid"]
        self.data["advies_ev"]         = se.advice_confirmed["ev"]

        try:
            financial, inverter_r, capacity, lifetime, summary = advisor_module.run_advisor(
                self._config, self.data, self._advisor_state,
            )
            self.data["advies_systeem_samenvatting"] = summary
            self.data["advies_financieel_v2"] = financial.label
            self.data["advies_financieel_v2_score"] = round(financial.score, 3)
            self.data["advies_financieel_v2_alt"] = financial.alternative or ""
            self.data["advies_omvormer_v2"] = inverter_r.label
            self.data["advies_omvormer_v2_score"] = round(inverter_r.score, 3)
            self.data["advies_omvormer_v2_alt"] = inverter_r.alternative or ""
            self.data["advies_capaciteit_v2"] = capacity.label
            self.data["advies_capaciteit_v2_score"] = round(capacity.score, 3)
            self.data["advies_levensduur_v2"] = lifetime.label
            self.data["advies_levensduur_v2_score"] = round(lifetime.score, 3)
        except Exception as exc:
            _LOGGER.warning("BatteryLabs: advisor.run_advisor faalde (%s)", exc)

        if (now - self._last_profile_save).total_seconds() >= PROFILE_SAVE_INTERVAL_S:
            self._last_profile_save = now
            await self._async_save_profile()

        for cb in self._listeners:
            try:
                cb()
            except Exception:
                pass

    async def update_logic(self, _=None):
        await self.handle_p1_update()
        await self.update_slow()


class BatterySensor(SensorEntity):
    def __init__(self, coordinator, name_suffix, data_key, unit, device_class, enabled: bool = True):
        self._coordinator = coordinator
        self._attr_name = f"BatteryLabs {name_suffix}"
        self._data_key = data_key
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        is_counter = data_key in ("energy_in", "energy_out")
        is_total = data_key in ("savings", "plan_savings_24h", "savings_per_year", "roi_perc")
        if is_counter:
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        elif is_total or device_class == SensorDeviceClass.MONETARY:
            self._attr_state_class = SensorStateClass.TOTAL
        else:
            self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_unique_id = f"bl_{data_key}_{coordinator._entry_id}"
        self._attr_should_poll = False
        self._attr_entity_registry_enabled_default = enabled

    async def async_added_to_hass(self):
        self._coordinator.register_listener(self._on_update)

    def _on_update(self):
        self.async_write_ha_state()

    @property
    def native_value(self):
        val = self._coordinator.data.get(self._data_key, 0)
        return round(val, 2) if isinstance(val, (int, float)) else val

    @property
    def extra_state_attributes(self) -> dict:
        return _build_attributes(self._coordinator, self._data_key)

    @property
    def device_info(self):
        return _device_info(self._coordinator)


class BatteryTextSensor(SensorEntity):
    def __init__(self, coordinator, name_suffix, data_key, icon, enabled: bool = True):
        self._coordinator = coordinator
        self._attr_name = f"BatteryLabs {name_suffix}"
        self._data_key = data_key
        self._attr_icon = icon
        self._attr_unique_id = f"bl_txt_{data_key}_{coordinator._entry_id}"
        self._attr_should_poll = False
        self._attr_entity_registry_enabled_default = enabled

    async def async_added_to_hass(self):
        self._coordinator.register_listener(self._on_update)

    def _on_update(self):
        self.async_write_ha_state()

    @property
    def native_value(self):
        value = self._coordinator.data.get(self._data_key, "N.v.t.")
        # HA rejects states longer than 255 characters: the state falls back
        # to unknown and an error is logged on every update. Truncate the
        # state; the full text stays available in the volledige_tekst
        # attribute below.
        if isinstance(value, str) and len(value) > 255:
            return value[:254] + "…"
        return value

    @property
    def extra_state_attributes(self) -> dict:
        attrs = _build_attributes(self._coordinator, self._data_key)
        value = self._coordinator.data.get(self._data_key)
        if isinstance(value, str) and len(value) > 255:
            attrs = {**(attrs or {}), "volledige_tekst": value}
        return attrs

    @property
    def device_info(self):
        return _device_info(self._coordinator)


class BatteryStatusSensor(SensorEntity):
    def __init__(self, coordinator):
        self._coordinator = coordinator
        self._attr_name = "BatteryLabs Systeem Status"
        self._attr_unique_id = f"bl_status_{coordinator._entry_id}"
        self._attr_should_poll = False

    async def async_added_to_hass(self):
        self._coordinator.register_listener(self._on_update)

    def _on_update(self):
        self.async_write_ha_state()

    @property
    def native_value(self):
        return self._coordinator.data.get("status", "Standby")

    @property
    def extra_state_attributes(self) -> dict:
        c = self._coordinator
        ad = c.data.get("_advisor_days", 0.0)
        pw = 0.0
        if ad >= 14: pw = 100.0
        elif ad >= 7: pw = (ad - 7) / 7 * 100
        return {
            "batterij_model": c._bat_profile.model,
            "inverter_model": c._inv_profile.model,
            "aantal_modules": c._modules,
            "capaciteit_kwh": round(c._cap_kwh, 2),
            "bruikbaar_kwh": round(c._usable_kwh, 2),
            "actieve_modus": c.data.get("mode"),
            "active_days": round(ad, 1),
            "profile_weight_pct": round(pw, 0),
            "optimizer_laag": (
                "Laag 3 (volledig)" if ad >= 14 else
                f"Laag 2 ({pw:.0f}% profiel)" if ad >= 7 else
                "Laag 1 (prijsarbitrage)"
            ),
            "peak_shaving_actief": c.data.get("peak_shaving_actief", False),
            "peak_shaving_drempel_w": c.data.get("peak_shaving_threshold_w", 2200.0),
            "peak_shaving_min_soc_pct": c.data.get("peak_shaving_min_soc", 15.0),
            "arbitrage_actief": c.data.get("arbitrage_actief", False),
            "dp_optimizer_actief": c.data.get("use_dp_optimizer", True),
            "dagspread_eur": c.data.get("day_spread_eur", 0.0),
        }

    @property
    def device_info(self):
        return _device_info(self._coordinator)


class BatteryInverterStatusSensor(SensorEntity):
    def __init__(self, coordinator, phase, data_key, enabled: bool = True):
        self._coordinator = coordinator
        self._attr_name = f"BatteryLabs Inverter {phase} Status"
        self._attr_unique_id = f"bl_stat_{phase}_{coordinator._entry_id}"
        self._data_key = data_key
        self._phase_idx = int(phase[1]) - 1
        self._attr_should_poll = False
        self._attr_entity_registry_enabled_default = enabled

    async def async_added_to_hass(self):
        self._coordinator.register_listener(self._on_update)

    def _on_update(self):
        self.async_write_ha_state()

    @property
    def native_value(self):
        return self._coordinator.data.get(self._data_key, "Standby")

    @property
    def extra_state_attributes(self) -> dict:
        c = self._coordinator
        p_key = f"p{self._phase_idx + 1}"
        t_key = f"t_inv{self._phase_idx + 1}"
        inv = c._inv_profile
        p = c.data.get(p_key, 0.0)
        t = c.data.get(t_key, 25.0)
        return {
            "inverter_model": inv.model,
            "vermogen_w": round(p, 1),
            "temperatuur_c": c.data.get(t_key),
            "max_vermogen_continu_w": inv.power_at_temp(t),
            "derotering_factor": round(inv.power_at_temp(t) / inv.power_cont_25c_w, 3),
            "rendement_huidig": round(inv.efficiency_at_load(abs(p)), 3),
            "nullast_vermogen_w": inv.no_load_power_w,
        }

    @property
    def device_info(self):
        return _device_info(self._coordinator)


class BatteryProfileSensor(SensorEntity):
    def __init__(self, coordinator):
        self._coordinator = coordinator
        self._attr_name = "BatteryLabs Leerprofiel Voortgang"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_icon = "mdi:brain"
        self._attr_unique_id = f"bl_profile_{coordinator._entry_id}"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_should_poll = False

    async def async_added_to_hass(self):
        self._coordinator.register_listener(self._on_update)

    def _on_update(self):
        self.async_write_ha_state()

    @property
    def native_value(self):
        return self._coordinator.data.get("profile_pct", 0.0)

    @property
    def extra_state_attributes(self) -> dict:
        c = self._coordinator
        ad = c.data.get("_advisor_days", 0.0)
        pw = 0.0
        if ad >= 14: pw = 100.0
        elif ad >= 7: pw = (ad - 7) / 7 * 100
        return {
            "status": c.data.get("profile_status"),
            "slots_gevuld": c.data.get("profile_slots_filled"),
            "slots_totaal": PROFILE_SLOTS_TOTAL,
            "dagen_tot_volgende_drempel": c.data.get("profile_days_to_next"),
            "actieve_dagen": round(ad, 1),
            "optimizer_laag": (
                "Laag 3 (volledig)" if ad >= 14 else
                f"Laag 2 ({pw:.0f}% profiel)" if ad >= 7 else
                "Laag 1 (prijsarbitrage)"
            ),
            "drempel_beperkt_actief_weken": PROFILE_WEEKS_ACTIVE,
            "drempel_betrouwbaar_weken": PROFILE_WEEKS_RELIABLE,
            "laatste_reset": c.data.get("profile_last_reset"),
            "ema_alpha": PROFILE_EMA_ALPHA,
        }

    @property
    def device_info(self):
        return _device_info(self._coordinator)


def _device_info(coordinator) -> dict:
    return {
        "identifiers": {(DOMAIN, coordinator._entry_id)},
        "name": "BatteryLabs Systeem",
        "manufacturer": "BatteryLabs",
        "model": "Smart 3-Phase Simulator",
        "sw_version": "4.0.0",
    }


def _plan_to_hourly_array(coordinator, now_utc, field, fallback):
    result = []
    base = now_utc.replace(minute=0, second=0, microsecond=0)
    for offset in range(24):
        entry = coordinator._plan_entry_at(base + timedelta(hours=offset))
        result.append(entry.get(field, fallback) if entry else fallback)
    return result


def _find_peak_hour(plan: dict, kind: str) -> str:
    if not plan:
        return "onbekend"
    if kind == "expensive":
        ts = max(plan.keys(), key=lambda k: plan[k].get("price_eur", 0))
    else:
        ts = min(plan.keys(), key=lambda k: plan[k].get("price_eur", 0))
    if hasattr(ts, "astimezone"):
        return ts.astimezone().strftime("%H:%M")


def _build_attributes(coordinator, data_key: str) -> dict:
    c = coordinator
    d = c.data
    bat = c._bat_profile
    inv = c._inv_profile

    if data_key == "soc":
        t_bat = d.get("t_bat", 25.0)
        return {
            "batterij_model": bat.model,
            "aantal_modules": c._modules,
            "capaciteit_kwh": round(c._cap_kwh, 2),
            "bruikbaar_kwh": round(c._usable_kwh, 2),
            "temp_correctie_factor": round(bat.capacity_factor_at_temp(t_bat), 3),
            "effectieve_capaciteit_kwh": round(c._cap_wh * bat.capacity_factor_at_temp(t_bat) / 1000, 2),
            "dod_limiet_pct": round(bat.dod_max * 100, 1),
            "min_soc_pct": c._config.get("min_soc", 10.0),
            "ocv_spanning_v": round(bat.voltage_at_soc(d.get("soc", 50.0) / 100), 2),
        }

    if data_key in ("p_total", "p1", "p2", "p3"):
        phase_map = {"p_total": None, "p1": 1, "p2": 2, "p3": 3}
        phase = phase_map[data_key]
        p = d.get(data_key, 0.0)
        t_inv = d.get(f"t_inv{phase}", 25.0) if phase else max(
            d.get("t_inv1", 25.0), d.get("t_inv2", 25.0), d.get("t_inv3", 25.0)
        )
        return {
            "inverter_model": inv.model,
            "max_vermogen_continu_w": round(inv.power_at_temp(t_inv) * (3 if not phase else 1), 1),
            "derotering_factor": round(inv.power_at_temp(t_inv) / inv.power_cont_25c_w, 3),
            "rendement_huidig": round(inv.efficiency_at_load(abs(p)), 3),
            "batterij_max_laad_w": round(bat.max_charge_power_w(c._modules, d.get("t_bat", 25.0)), 1),
            "batterij_max_ontlaad_w": round(bat.max_discharge_power_w(c._modules, d.get("t_bat", 25.0)), 1),
        }

    if data_key == "v_dc":
        return {
            "batterij_model": bat.model,
            "nominale_spanning_v": bat.nominal_voltage_v,
            "min_spanning_ontladen_v": bat.voltage_discharge_min_v,
            "max_spanning_laden_v": bat.voltage_charge_max_v,
            "absorptie_spanning_v": inv.charge_voltage_absorption_v,
            "float_spanning_v": inv.charge_voltage_float_v,
        }

    if data_key == "i_dc":
        return {
            "aanbevolen_stroom_a": bat.current_recommended_a * c._modules,
            "max_stroom_15min_a": bat.current_max_15min_a * c._modules,
            "piekstroom_15s_a": bat.current_peak_15s_a * c._modules,
        }

    if data_key == "soh":
        return {
            "batterij_model": bat.model,
            "cycluslevensduur": bat.cycle_life,
            "ontwerplengte_jaren": bat.design_life_years,
            "cycli_tot_nu": round(d.get("cycles", 0.0), 2),
            "verwachte_resterende_cycli": max(0, round(bat.cycle_life - d.get("cycles", 0.0))),
            "soh_drempel_warning_pct": SOH_WARNING_THRESHOLD,
            "degradatie_rate_pct_per_maand": d.get("soh_degradation_rate", 0.0),
        }

    if data_key == "cycles":
        return {
            "cycluslevensduur_totaal": bat.cycle_life,
            "resterende_cycli": max(0, round(bat.cycle_life - d.get("cycles", 0.0))),
            "rte_pct": d.get("rte", 100.0),
            "energie_in_kwh": round(d.get("energy_in", 0.0), 3),
            "energie_uit_kwh": round(d.get("energy_out", 0.0), 3),
        }

    if data_key == "savings":
        system_cost = c._config.get("system_cost_euro", 15000.0)
        savings = d.get("savings", 0.0)
        energy_out = d.get("energy_out", 0.0)
        if savings > 0.01 and energy_out > 0:
            avg_price_per_kwh = savings / energy_out
            kwh_needed = system_cost / avg_price_per_kwh if avg_price_per_kwh > 0 else 0
            pct_done = (energy_out / kwh_needed * 100) if kwh_needed > 0 else 0
        else:
            pct_done = 0.0
        return {
            "systeem_kostprijs_euro": system_cost,
            "roi_pct": round(d.get("roi_perc", 0.0), 2),
            "totaal_ontladen_kwh": round(d.get("energy_out", 0.0), 3),
            "gemiddelde_prijs_bij_ontladen": round(
                savings / max(d.get("energy_out", 0.001), 0.001), 4
            ),
            "break_even_voortgang_pct": round(pct_done, 1),
            "verwachte_jaarlijkse_besparing_euro": d.get("savings_per_year", 0.0),
            "installatie_datum": d.get("install_date", "onbekend"),
        }

    if data_key == "savings_per_year":
        savings = d.get("savings", 0.0)
        install_date = d.get("install_date", "onbekend")
        try:
            from datetime import datetime as _dt
            install_dt = _dt.strptime(install_date, "%Y-%m-%d")
            days_active = max(1.0, (_dt.now() - install_dt).total_seconds() / 86400)
        except Exception:
            days_active = 1.0
        return {
            "basis": "Huidige besparingssnelheid × 365 dagen",
            "totale_besparing_tot_nu_euro": round(savings, 4),
            "actief_sinds": install_date,
            "actieve_dagen": round(days_active, 1),
            "besparing_per_dag_euro": round(savings / max(days_active, 1), 4),
            "nauwkeurigheid": (
                "Laag (< 7 dagen data)" if days_active < 7
                else "Matig (< 30 dagen data)" if days_active < 30
                else "Goed (30+ dagen data)"
            ),
        }

    if data_key == "t_bat":
        t = d.get("t_bat", 20.0)
        return {
            "batterij_model": bat.model,
            "min_laad_temp_c": bat.temp_charge_min_c,
            "max_laad_temp_c": bat.temp_charge_max_c,
            "min_ontlaad_temp_c": bat.temp_discharge_min_c,
            "max_ontlaad_temp_c": bat.temp_discharge_max_c,
            "warning_drempel_hoog_c": TEMP_BAT_WARNING_HIGH,
            "caution_drempel_laag_c": TEMP_BAT_CAUTION_LOW,
            "laden_toegestaan": t >= bat.temp_charge_min_c,
            "ontladen_toegestaan": t >= bat.temp_discharge_min_c,
        }

    if data_key == "health_msg":
        return {
            "t_bat_c": d.get("t_bat"),
            "soc_pct": round(d.get("soc", 0.0), 1),
            "soh_pct": round(d.get("soh", 100.0), 1),
            "temp_warning_hoog_c": TEMP_BAT_WARNING_HIGH,
            "temp_caution_laag_c": TEMP_BAT_CAUTION_LOW,
            "soh_warning_drempel_pct": SOH_WARNING_THRESHOLD,
        }

    if data_key in ("plan_action", "plan_next_action"):
        now_utc = datetime.now(timezone.utc)
        plan = d.get("_plan_full", {})
        entry = c._plan_entry_at(now_utc)
        reden = entry.get("reason", "")
        if d.get("peak_shaving_actief") and "Vasthouden" in entry.get("action", ""):
            reden = (
                f"{reden} | LET OP: DP-plan adviseert vasthouden, maar eigenverbruik/"
                f"piekshaving is nu actief en ontlaadt de batterij om huisverbruik te "
                f"dekken (drempel {d.get('peak_shaving_threshold_w', 2200.0)/1000:.1f} kW/fase). "
                f"Dit heeft voorrang op het DP-plan."
            )
        return {
            "reden": reden,
            "prijs_huidig_uur_eur": entry.get("price_eur", d.get("_price_now", 0.0)),
            "duurste_uur_vandaag": _find_peak_hour(plan, "expensive"),
            "goedkoopste_uur_vandaag": _find_peak_hour(plan, "cheap"),
            "plan_actief": bool(plan),
            "sustainability_score": entry.get("sustainability", 0),
            "plan_stap_minuten": round((c._plan_step_hours or 1.0) * 60),
            "soc_forecast_24h": _plan_to_hourly_array(c, now_utc, "target_soc", d.get("soc", 50.0)),
            "prijs_forecast_24h": _plan_to_hourly_array(c, now_utc, "price_eur", d.get("_price_now", 0.0)),
            "verbruik_forecast_24h": d.get("verbruik_forecast_w", []),
            "pv_forecast_24h": d.get("_pv_hourly", []),
        }

    if data_key == "plan_soc_target":
        return {
            "profiel_voortgang_pct": d.get("profile_pct", 0.0),
            "profiel_status": d.get("profile_status"),
            "min_soc_pct": c._config.get("min_soc", 10.0),
            "soc_buffer_pct": OPTIMIZER_SOC_BUFFER_PCT,
        }

    if data_key == "_arbitrage_depth_pct":
        return {
            "arbitrage_actief": d.get("arbitrage_actief", False),
            "dagspread_eur": d.get("day_spread_eur", 0.0),
            "drempel_min_eur": PRICE_SPREAD_MIN_EUR,
            "drempel_max_eur": PRICE_SPREAD_MAX_EUR,
            "max_diepte_pct": PRICE_SPREAD_MAX_DEPTH_PCT,
        }

    if data_key == "day_spread_eur":
        return {
            "arbitrage_actief": d.get("arbitrage_actief", False),
            "arbitrage_diepte_pct": d.get("_arbitrage_depth_pct", 0.0),
            "drempel_min_eur": PRICE_SPREAD_MIN_EUR,
            "drempel_max_eur": PRICE_SPREAD_MAX_EUR,
        }

    if data_key == "pv_forecast_today_kwh":
        pv_hourly = d.get("_pv_hourly", [])
        return {
            "pv_aanwezig": c._config.get("pv_present", False),
            "forecast_sensor": c._config.get("solar_forecast_sensor", ""),
            "uurverdeling_wh": [round(v, 1) for v in pv_hourly],
            "piek_uur": (
                pv_hourly.index(max(pv_hourly)) if pv_hourly and max(pv_hourly) > 0 else None
            ),
        }

    if data_key in ("advies_financieel_v2", "advies_omvormer_v2", "advies_capaciteit_v2", "advies_levensduur_v2"):
        base = data_key.replace("advies_", "").replace("_v2", "")
        score = d.get(f"advies_{base}_v2_score", 0.5)
        return {
            "score_0_1": score,
            "alternatief": d.get(f"advies_{base}_v2_alt", ""),
            "systeem_kostprijs_euro": c._config.get("system_cost_euro", 15000.0),
            "huidige_hardware": f"{c._bat_profile.model} x{c._modules} + {c._inv_profile.model}",
            "actieve_dagen": round(d.get("_advisor_days", 0.0), 1),
            "samenvatting": d.get("advies_systeem_samenvatting", ""),
        }

    if data_key == "plan_savings_24h":
        return {
            "basis": "Geschatte ontlading × verwachte prijs per duur uur",
            "plan_horizon_uur": OPTIMIZER_PLAN_HORIZON_H,
            "profiel_betrouwbaar": d.get("profile_pct", 0) >= 100,
        }

    return {}
