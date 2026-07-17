"""
Hardware profiles voor BatteryLabs 3-Phase simulatie.

Alle waarden zijn afkomstig uit officiële datasheets:
  - Pylontech US Series (US2000C / US3000C / US5000)
  - Victron MultiPlus-II 230V 48V modellen

Geen logica in dit bestand — alleen pure datastructuren.
"""
from dataclasses import dataclass, field
from typing import List, Tuple


# ---------------------------------------------------------------------------
# Pylontech US-serie
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PylontechProfile:
    """
    Datasheet-parameters voor één Pylontech US-module.
    Alle stroom/spanning/capaciteitswaarden gelden per module.
    Bij meerdere modules parallel schaalt capaciteit lineair;
    stroom schaalt ook lineair maar de BMS-limieten gelden per module.
    """
    model: str
    nominal_voltage_v: float          # V nominaal
    capacity_kwh: float               # kWh nominaal per module
    usable_kwh: float                 # kWh bruikbaar (95% DoD)
    dod_max: float                    # Max diepte van ontlading (0–1)

    # Stroom (A) per module — datasheet waarden
    current_recommended_a: float      # Aanbevolen continu (laden én ontladen)
    current_max_15min_a: float        # Maximum 15 minuten
    current_peak_15s_a: float         # Piekstroom 15 seconden

    # Spanningsbereiken (V)
    voltage_discharge_min_v: float    # Laagste ontlaadspanning
    voltage_discharge_max_v: float    # Hoogste ontlaadspanning
    voltage_charge_min_v: float       # Minimale laadspanning
    voltage_charge_max_v: float       # Maximale laadspanning (absorptie)

    # Prestaties
    rte: float                        # Round-trip efficiency (0–1)
    cycle_life: int                   # Cycluslevensduur bij 25°C 90% DoD
    design_life_years: int            # Ontwerplengte in jaren

    # Temperatuurgrenzen (°C)
    temp_charge_min_c: float          # Minimale temperatuur bij laden
    temp_charge_max_c: float          # Maximale temperatuur bij laden
    temp_discharge_min_c: float       # Minimale temperatuur bij ontladen
    temp_discharge_max_c: float       # Maximale temperatuur bij ontladen

    # OCV-curve: lijst van (soc_fraction, voltage) knooppunten
    # Lineaire interpolatie tussen knooppunten geeft spanning bij elk SoC-punt.
    # Gebaseerd op typisch LFP-spanningsprofiel (vlak plateau 10–90%).
    ocv_curve: List[Tuple[float, float]] = field(default_factory=list)

    # Temperatuurcorrectie op bruikbare capaciteit
    # Lijst van (temp_c, capaciteit_factor) knooppunten — lineaire interpolatie.
    temp_capacity_curve: List[Tuple[float, float]] = field(default_factory=list)

    def voltage_at_soc(self, soc_fraction: float) -> float:
        """Geeft interpoleerde OCV-spanning bij gegeven SoC (0–1)."""
        soc_fraction = max(0.0, min(1.0, soc_fraction))
        curve = self.ocv_curve
        if not curve:
            return self.nominal_voltage_v
        if soc_fraction <= curve[0][0]:
            return curve[0][1]
        if soc_fraction >= curve[-1][0]:
            return curve[-1][1]
        for i in range(len(curve) - 1):
            s0, v0 = curve[i]
            s1, v1 = curve[i + 1]
            if s0 <= soc_fraction <= s1:
                t = (soc_fraction - s0) / (s1 - s0)
                return v0 + t * (v1 - v0)
        return self.nominal_voltage_v

    def capacity_factor_at_temp(self, temp_c: float) -> float:
        """Geeft capaciteitsfactor (0–1) bij gegeven temperatuur."""
        curve = self.temp_capacity_curve
        if not curve:
            return 1.0
        if temp_c <= curve[0][0]:
            return curve[0][1]
        if temp_c >= curve[-1][0]:
            return curve[-1][1]
        for i in range(len(curve) - 1):
            t0, f0 = curve[i]
            t1, f1 = curve[i + 1]
            if t0 <= temp_c <= t1:
                t = (temp_c - t0) / (t1 - t0)
                return f0 + t * (f1 - f0)
        return 1.0

    def max_charge_power_w(self, modules: int, temp_c: float = 25.0) -> float:
        """
        Maximaal laadvermogen in W voor het gehele battrijpakket.
        Begrensd door aanbevolen stroom × spanning × modules.
        Laden geblokkeerd onder minimale laadtemperatuur.
        """
        if temp_c < self.temp_charge_min_c:
            return 0.0
        v = self.voltage_at_soc(0.5)  # Middenspanning als conservatieve schatting
        return self.current_recommended_a * v * modules

    def max_discharge_power_w(self, modules: int, temp_c: float = 25.0) -> float:
        """Maximaal ontlaadvermogen in W voor het gehele batterijpakket."""
        if temp_c < self.temp_discharge_min_c:
            return 0.0
        v = self.voltage_at_soc(0.5)
        return self.current_recommended_a * v * modules

    def degradation_per_cycle(self, dod_fraction: float) -> float:
        """
        SoH-verlies per equivalente volledige cyclus op basis van DoD.
        Bij 90% DoD: cycle_life cycli tot 80% SoH → 20% verlies over cycle_life cycli.
        Ondiepe cycli slijten minder: factor schaalt kwadratisch met DoD.
        """
        # 20% SoH-verlies over cycle_life cycli bij referentie-DoD van 0.9
        base_loss_per_cycle = 0.20 / self.cycle_life
        dod_factor = (dod_fraction / 0.9) ** 2
        return base_loss_per_cycle * dod_factor


# LFP OCV-curve knooppunten — typisch Pylontech US profiel
# (soc_fraction, voltage_v)
_LFP_OCV_CURVE = [
    (0.00, 44.5),
    (0.05, 46.0),
    (0.10, 47.5),
    (0.20, 51.0),
    (0.50, 51.8),
    (0.80, 52.5),
    (0.90, 52.9),
    (0.95, 53.2),
    (1.00, 53.5),
]

# Capaciteitscorrectie op temperatuur — LFP gedrag
# (temp_c, capacity_factor)
_LFP_TEMP_CAPACITY = [
    (-10.0, 0.60),
    (  0.0, 0.80),
    (  5.0, 0.90),
    ( 15.0, 0.97),
    ( 25.0, 1.00),
    ( 45.0, 1.00),
    ( 55.0, 0.97),
]


PYLONTECH_PROFILES = {
    "US2000C": PylontechProfile(
        model="US2000C",
        nominal_voltage_v=48.0,
        capacity_kwh=2.4,
        usable_kwh=2.28,
        dod_max=0.95,
        current_recommended_a=25.0,
        current_max_15min_a=50.0,
        current_peak_15s_a=200.0,
        voltage_discharge_min_v=44.5,
        voltage_discharge_max_v=53.5,
        voltage_charge_min_v=52.5,
        voltage_charge_max_v=53.5,
        rte=0.95,
        cycle_life=8000,
        design_life_years=15,
        temp_charge_min_c=0.0,
        temp_charge_max_c=55.0,
        temp_discharge_min_c=-10.0,
        temp_discharge_max_c=55.0,
        ocv_curve=_LFP_OCV_CURVE,
        temp_capacity_curve=_LFP_TEMP_CAPACITY,
    ),
    "US3000C": PylontechProfile(
        model="US3000C",
        nominal_voltage_v=48.0,
        capacity_kwh=3.55,
        usable_kwh=3.37,
        dod_max=0.95,
        current_recommended_a=37.0,
        current_max_15min_a=74.0,
        current_peak_15s_a=200.0,
        voltage_discharge_min_v=44.5,
        voltage_discharge_max_v=53.5,
        voltage_charge_min_v=52.5,
        voltage_charge_max_v=53.5,
        rte=0.95,
        cycle_life=8000,
        design_life_years=15,
        temp_charge_min_c=0.0,
        temp_charge_max_c=55.0,
        temp_discharge_min_c=-10.0,
        temp_discharge_max_c=55.0,
        ocv_curve=_LFP_OCV_CURVE,
        temp_capacity_curve=_LFP_TEMP_CAPACITY,
    ),
    "US5000": PylontechProfile(
        model="US5000",
        nominal_voltage_v=48.0,
        capacity_kwh=4.8,
        usable_kwh=4.56,
        dod_max=0.95,
        current_recommended_a=75.0,
        current_max_15min_a=120.0,
        current_peak_15s_a=200.0,
        voltage_discharge_min_v=44.5,
        voltage_discharge_max_v=53.5,
        voltage_charge_min_v=52.5,
        voltage_charge_max_v=53.5,
        rte=0.95,
        cycle_life=8000,
        design_life_years=15,
        temp_charge_min_c=0.0,
        temp_charge_max_c=55.0,
        temp_discharge_min_c=-10.0,
        temp_discharge_max_c=55.0,
        ocv_curve=_LFP_OCV_CURVE,
        temp_capacity_curve=_LFP_TEMP_CAPACITY,
    ),
}


# ---------------------------------------------------------------------------
# Victron MultiPlus-II 230V 48V
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VictronProfile:
    """
    Datasheet-parameters voor één Victron MultiPlus-II unit.
    In een 3-fase opstelling zijn er 3 identieke units (één per fase).
    Alle vermogens zijn per unit.
    """
    model: str

    # Omvormer — vermogen per unit (W)
    power_cont_25c_w: float           # Continu bij 25°C
    power_cont_40c_w: float           # Continu bij 40°C (derotering)
    power_cont_65c_w: float           # Continu bij 65°C (derotering)
    power_peak_w: float               # Piekvermogen

    # Lader
    charge_current_max_a: float       # Maximale laadstroom (A)
    charge_voltage_absorption_v: float  # Absorptielaadspanning (48V systeem)
    charge_voltage_float_v: float     # Float-spanning
    charge_voltage_storage_v: float   # Opslagspanning

    # Efficiëntie
    efficiency_max: float             # Maximale efficiëntie (0–1)
    no_load_power_w: float            # Nullastvermogen normaal (W)
    no_load_power_aes_w: float        # Nullastvermogen AES-modus (W)

    # Temperatuurbereik
    temp_operating_min_c: float       # Minimum bedrijfstemperatuur
    temp_operating_max_c: float       # Maximum bedrijfstemperatuur

    # AC transfer
    transfer_switch_a: float          # Transfer-schakelaar (A)
    ac_input_max_a: float             # Maximale AC-ingangsstroom

    def power_at_temp(self, temp_c: float) -> float:
        """
        Geeft maximaal continu vermogen bij gegeven omvormertemperatuur.
        Lineaire interpolatie tussen de drie deroteringsdrempelwaarden.
        """
        if temp_c <= 25.0:
            return self.power_cont_25c_w
        if temp_c <= 40.0:
            t = (temp_c - 25.0) / 15.0
            return self.power_cont_25c_w + t * (self.power_cont_40c_w - self.power_cont_25c_w)
        if temp_c <= 65.0:
            t = (temp_c - 40.0) / 25.0
            return self.power_cont_40c_w + t * (self.power_cont_65c_w - self.power_cont_40c_w)
        return self.power_cont_65c_w

    def efficiency_at_load(self, p_w: float) -> float:
        """
        Kwadratisch rendementsmodel op basis van relatieve belasting.
        Rendement is het laagst bij lage belasting en stijgt monotoon naar
        efficiency_max bij volledige belasting. Dit modelleert het dominante
        effect: het lage-belasting rendementsdal van moderne omvormers.
        (Vereenvoudiging: de lichte terugval bij 100% t.o.v. ~75% wordt niet
        gemodelleerd — verwaarloosbaar voor deze simulatie.)

        eff(p) = eff_max - k × (1 - p/p_max)²

        k = 0.08 geeft een rendementsdal van ~8% bij nullast.
        """
        if p_w <= 0:
            return 0.0
        p_max = self.power_cont_25c_w
        load_ratio = min(p_w / p_max, 1.0)
        k = 0.08
        eff = self.efficiency_max - k * (1.0 - load_ratio) ** 2
        return max(0.70, min(self.efficiency_max, eff))

    def effective_power_out(self, p_dc_w: float, temp_c: float = 25.0) -> float:
        """
        Effectief AC-vermogen na aftrek van omvormerverliezen en nullast.
        p_dc_w: DC-vermogen vanuit de batterij (positief = ontladen)
        Retourneert AC-vermogen (netto geleverd aan huis/net).
        """
        p_max = self.power_at_temp(temp_c)
        p_dc_w = min(p_dc_w, p_max)
        eff = self.efficiency_at_load(p_dc_w)
        return p_dc_w * eff - self.no_load_power_w


VICTRON_PROFILES = {
    "MultiPlus-II 48/3000": VictronProfile(
        model="MultiPlus-II 48/3000",
        power_cont_25c_w=2400.0,
        power_cont_40c_w=2200.0,
        power_cont_65c_w=1700.0,
        power_peak_w=5500.0,
        charge_current_max_a=35.0,
        charge_voltage_absorption_v=57.6,
        charge_voltage_float_v=55.2,
        charge_voltage_storage_v=52.8,
        efficiency_max=0.95,
        no_load_power_w=11.0,
        no_load_power_aes_w=7.0,
        temp_operating_min_c=-40.0,
        temp_operating_max_c=65.0,
        transfer_switch_a=32.0,
        ac_input_max_a=32.0,
    ),
    "MultiPlus-II 48/5000": VictronProfile(
        model="MultiPlus-II 48/5000",
        power_cont_25c_w=4000.0,
        power_cont_40c_w=3700.0,
        power_cont_65c_w=3000.0,
        power_peak_w=9000.0,
        charge_current_max_a=70.0,
        charge_voltage_absorption_v=57.6,
        charge_voltage_float_v=55.2,
        charge_voltage_storage_v=52.8,
        efficiency_max=0.96,
        no_load_power_w=18.0,
        no_load_power_aes_w=12.0,
        temp_operating_min_c=-40.0,
        temp_operating_max_c=65.0,
        transfer_switch_a=50.0,
        ac_input_max_a=50.0,
    ),
    "MultiPlus-II 48/8000": VictronProfile(
        model="MultiPlus-II 48/8000",
        power_cont_25c_w=6400.0,
        power_cont_40c_w=5500.0,
        power_cont_65c_w=4000.0,
        power_peak_w=15000.0,
        charge_current_max_a=110.0,
        charge_voltage_absorption_v=57.6,
        charge_voltage_float_v=55.2,
        charge_voltage_storage_v=52.8,
        efficiency_max=0.95,
        no_load_power_w=29.0,
        no_load_power_aes_w=19.0,
        temp_operating_min_c=-40.0,
        temp_operating_max_c=65.0,
        transfer_switch_a=100.0,
        ac_input_max_a=100.0,
    ),
    "MultiPlus-II 48/10000": VictronProfile(
        model="MultiPlus-II 48/10000",
        power_cont_25c_w=8000.0,
        power_cont_40c_w=7000.0,
        power_cont_65c_w=6000.0,
        power_peak_w=18000.0,
        charge_current_max_a=140.0,
        charge_voltage_absorption_v=57.6,
        charge_voltage_float_v=55.2,
        charge_voltage_storage_v=52.8,
        efficiency_max=0.96,
        no_load_power_w=38.0,
        no_load_power_aes_w=27.0,
        temp_operating_min_c=-40.0,
        temp_operating_max_c=65.0,
        transfer_switch_a=100.0,
        ac_input_max_a=100.0,
    ),
    "MultiPlus-II 48/15000": VictronProfile(
        model="MultiPlus-II 48/15000",
        power_cont_25c_w=12000.0,
        power_cont_40c_w=10000.0,
        power_cont_65c_w=7000.0,
        power_peak_w=27000.0,
        charge_current_max_a=200.0,
        charge_voltage_absorption_v=57.6,
        charge_voltage_float_v=55.2,
        charge_voltage_storage_v=52.8,
        efficiency_max=0.95,
        no_load_power_w=55.0,
        no_load_power_aes_w=39.0,
        temp_operating_min_c=-40.0,
        temp_operating_max_c=65.0,
        transfer_switch_a=100.0,
        ac_input_max_a=100.0,
    ),
}
