"""
BatteryLabs 3-Phase — Systeemadviseur

Analyseert de verzamelde meetdata en vergelijkt de geconfigureerde hardware
met alternatieven uit de hardware profielen. Geeft per dimensie een label,
score en onderbouwing terug.

Stabiliteitsmodel:
  Een advies wijzigt alleen als de nieuwe score significant afwijkt van
  het vorige gepubliceerde advies. De drempel voor "significant" neemt af
  naarmate er meer data beschikbaar is — zodat het advies in het begin
  voorzichtig is en na verloop van tijd stabiel.

Prioriteit samenvatting: Financieel → Omvormer → Capaciteit → Levensduur
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .const import (
    ADVISOR_MIN_DAYS,
    ADVISOR_STABILITY_14D, ADVISOR_STABILITY_30D, ADVISOR_STABILITY_90D,
    ADVISOR_INV_OVERLOAD_PCT, ADVISOR_INV_UNDERLOAD_PCT,
    ADVISOR_CAP_EMPTY_PCT, ADVISOR_CAP_SURPLUS_SOC,
    ADVISOR_DOD_HEALTHY_MIN, ADVISOR_DOD_HEALTHY_MAX, ADVISOR_DOD_HIGH_WEAR,
    ADVISOR_LABEL_OPTIMAL, ADVISOR_LABEL_TOO_SMALL, ADVISOR_LABEL_OVERSIZED,
    ADVISOR_LABEL_UNDERPOWER, ADVISOR_LABEL_HEALTHY,
    ADVISOR_LABEL_HIGH_WEAR, ADVISOR_LABEL_UNDERUSED,
    ADVISOR_LABEL_ALT_AVAILABLE, ADVISOR_LABEL_INSUFFICIENT_DATA,
)
from .hardware_profiles import PYLONTECH_PROFILES, VICTRON_PROFILES

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataklassen
# ---------------------------------------------------------------------------

@dataclass
class DimensionResult:
    """Resultaat van één beoordelingsdimensie."""
    label: str                          # Huidig advies-label
    score: float                        # Score 0.0–1.0 (1.0 = optimaal)
    summary: str                        # Menselijke toelichting
    alternative: Optional[str]          # Beste alternatief (of None)
    alternative_reason: str             # Waarom dat alternatief beter is
    days_of_data: float                 # Hoeveel dagen data achter dit advies
    confidence: str                     # "Laag" / "Matig" / "Goed"
    last_changed: str                   # Datum laatste advieswijziging


@dataclass
class AdvisorState:
    """
    Persistente staat van de adviseur — wordt opgeslagen in het profile JSON.
    Bevat de vorige gepubliceerde resultaten per dimensie voor stabiliteitscheck.
    """
    # Vorige gepubliceerde scores per dimensie
    prev_financial_score: float = 0.5
    prev_inverter_score: float = 0.5
    prev_capacity_score: float = 0.5
    prev_lifetime_score: float = 0.5

    # Datums laatste wijziging
    financial_changed: str = "Nooit"
    inverter_changed: str = "Nooit"
    capacity_changed: str = "Nooit"
    lifetime_changed: str = "Nooit"

    # Meethistorie voor capaciteitsanalyse
    # Lijst van (datum_str, eind_soc, leeg_voor_23) tuples — max 90 entries
    daily_records: list = field(default_factory=list)

    # Piekvermogens per fase — rollend maximum over 30 dagen
    peak_power_l1: float = 0.0
    peak_power_l2: float = 0.0
    peak_power_l3: float = 0.0
    peak_power_date: str = ""


# ---------------------------------------------------------------------------
# Hulpfuncties
# ---------------------------------------------------------------------------

def _confidence(days: float) -> str:
    if days < 7:
        return "Laag"
    if days < 30:
        return "Matig"
    return "Goed"


def _stability_threshold(days: float) -> float:
    """Minimale score-afwijking voor advieswijziging op basis van beschikbare data."""
    if days < 30:
        return ADVISOR_STABILITY_14D
    if days < 90:
        return ADVISOR_STABILITY_30D
    return ADVISOR_STABILITY_90D


def _should_update(prev_score: float, new_score: float, days: float) -> bool:
    """Bepaalt of een nieuw advies gepubliceerd mag worden."""
    threshold = _stability_threshold(days)
    return abs(new_score - prev_score) >= threshold


def _days_active(install_date: str) -> float:
    try:
        install_dt = datetime.strptime(install_date, "%Y-%m-%d")
        return max(1.0, (datetime.now() - install_dt).total_seconds() / 86400)
    except Exception:
        return 1.0


# ---------------------------------------------------------------------------
# Dimensie: Financieel
# ---------------------------------------------------------------------------

def _analyze_financial(
    config: dict,
    coordinator_data: dict,
    days: float,
    state: AdvisorState,
) -> DimensionResult:
    """
    Vergelijkt terugverdientijd van huidige configuratie met alle alternatieven.
    Beste alternatief = combinatie met laagste terugverdientijd.
    """
    savings = coordinator_data.get("savings", 0.0)
    system_cost = config.get("system_cost_euro", 15000.0)
    current_bat = config.get("battery_model", "US5000")
    current_inv = config.get("inverter_model", "MultiPlus-II 48/5000")
    modules = int(config.get("battery_modules", 1))

    if savings < 0.01 or days < ADVISOR_MIN_DAYS:
        return DimensionResult(
            label=ADVISOR_LABEL_INSUFFICIENT_DATA,
            score=0.5,
            summary=f"Nog onvoldoende data ({days:.0f}/{ADVISOR_MIN_DAYS} dagen).",
            alternative=None,
            alternative_reason="",
            days_of_data=days,
            confidence=_confidence(days),
            last_changed=state.financial_changed,
        )

    savings_per_day = savings / days
    if savings_per_day <= 0:
        return DimensionResult(
            label=ADVISOR_LABEL_INSUFFICIENT_DATA,
            score=0.5,
            summary="Nog geen besparing gemeten.",
            alternative=None,
            alternative_reason="",
            days_of_data=days,
            confidence=_confidence(days),
            last_changed=state.financial_changed,
        )

    # Bereken terugverdientijd huidige config
    current_payback_years = (system_cost / (savings_per_day * 365))

    # Schat kostprijs alternatieve configuraties
    # Vaste module-kostprijs op basis van model (ruwe marktschatting)
    bat_cost_per_module = {
        "US2000C": 800.0,
        "US3000C": 1100.0,
        "US5000": 1600.0,
    }
    inv_cost = {
        "MultiPlus-II 48/3000": 1200.0,
        "MultiPlus-II 48/5000": 1800.0,
        "MultiPlus-II 48/8000": 2800.0,
        "MultiPlus-II 48/10000": 3500.0,
        "MultiPlus-II 48/15000": 5000.0,
    }

    best_payback = current_payback_years
    best_config = None
    best_reason = ""

    # Schaal de besparing naar andere capaciteiten
    current_cap_kwh = PYLONTECH_PROFILES[current_bat].capacity_kwh * modules

    for bat_model, bat_profile in PYLONTECH_PROFILES.items():
        for inv_model in VICTRON_PROFILES:
            for n_modules in range(1, 17):
                # Sla huidige config over
                if bat_model == current_bat and inv_model == current_inv and n_modules == modules:
                    continue

                alt_cap_kwh = bat_profile.capacity_kwh * n_modules
                # Schat besparing lineair op basis van capaciteitsverhouding
                # (meer capaciteit = meer buffermogelijkheid = meer besparing)
                # Begrensd op 2× want meer capaciteit dan dagverbruik helpt weinig
                cap_ratio = min(alt_cap_kwh / max(current_cap_kwh, 0.1), 2.0)
                alt_savings_per_day = savings_per_day * cap_ratio

                alt_cost = (
                    bat_cost_per_module.get(bat_model, 1200.0) * n_modules
                    + inv_cost.get(inv_model, 1800.0) * 3  # 3 units voor 3-fase
                )
                if alt_savings_per_day <= 0:
                    continue

                alt_payback = alt_cost / (alt_savings_per_day * 365)

                if alt_payback < best_payback * 0.90:  # Minimaal 10% beter
                    best_payback = alt_payback
                    best_config = f"{n_modules}× {bat_model} + {inv_model}"
                    best_reason = (
                        f"Terugverdientijd {alt_payback:.1f} jaar "
                        f"vs huidige {current_payback_years:.1f} jaar"
                    )

    # Score: hoe dichter bij 7 jaar terugverdientijd, hoe beter (schaal 5-15j)
    target_payback = 7.0
    score = max(0.0, min(1.0, 1.0 - abs(current_payback_years - target_payback) / 10.0))

    if best_config:
        label = ADVISOR_LABEL_ALT_AVAILABLE
        summary = (
            f"Huidige terugverdientijd: {current_payback_years:.1f} jaar. "
            f"Betere ROI mogelijk met {best_config}."
        )
    else:
        label = ADVISOR_LABEL_OPTIMAL
        summary = f"Terugverdientijd {current_payback_years:.1f} jaar — geen betere configuratie gevonden."
        best_reason = ""

    # Stabiliteitscheck — bij geen significante wijziging publiceren we de
    # vorige, stabiele uitkomst. Label, score én summary blijven onderling
    # consistent (anders kon label "Optimaal" zeggen terwijl de summary een
    # alternatief aanraadt).
    if not _should_update(state.prev_financial_score, score, days):
        score = state.prev_financial_score
        if score >= 0.6:
            label = ADVISOR_LABEL_OPTIMAL
            summary = (
                f"Configuratie stabiel — terugverdientijd "
                f"{current_payback_years:.1f} jaar, geen wijziging geadviseerd."
            )
            best_config = None
            best_reason = ""
        else:
            label = ADVISOR_LABEL_ALT_AVAILABLE
            if best_config:
                summary = (
                    f"Huidige terugverdientijd: {current_payback_years:.1f} jaar. "
                    f"Betere ROI mogelijk met {best_config}."
                )
            else:
                summary = (
                    f"Huidige terugverdientijd: {current_payback_years:.1f} jaar. "
                    f"Mogelijk een efficiëntere configuratie beschikbaar."
                )

    return DimensionResult(
        label=label,
        score=score,
        summary=summary,
        alternative=best_config,
        alternative_reason=best_reason,
        days_of_data=days,
        confidence=_confidence(days),
        last_changed=state.financial_changed,
    )


# ---------------------------------------------------------------------------
# Dimensie: Omvormer
# ---------------------------------------------------------------------------

def _analyze_inverter(
    config: dict,
    coordinator_data: dict,
    days: float,
    state: AdvisorState,
) -> DimensionResult:
    """
    Vergelijkt gemeten piekvermogens per fase met omvormerlimiet.
    """
    from .hardware_profiles import VICTRON_PROFILES

    inv_model = config.get("inverter_model", "MultiPlus-II 48/5000")
    inv = VICTRON_PROFILES.get(inv_model)
    if not inv:
        return DimensionResult(
            label=ADVISOR_LABEL_INSUFFICIENT_DATA, score=0.5,
            summary="Omvormerprofiel niet gevonden.",
            alternative=None, alternative_reason="",
            days_of_data=days, confidence=_confidence(days),
            last_changed=state.inverter_changed,
        )

    if days < ADVISOR_MIN_DAYS:
        return DimensionResult(
            label=ADVISOR_LABEL_INSUFFICIENT_DATA, score=0.5,
            summary=f"Nog onvoldoende data ({days:.0f}/{ADVISOR_MIN_DAYS} dagen).",
            alternative=None, alternative_reason="",
            days_of_data=days, confidence=_confidence(days),
            last_changed=state.inverter_changed,
        )

    max_peak = max(
        state.peak_power_l1,
        state.peak_power_l2,
        state.peak_power_l3,
    )
    inv_limit = inv.power_cont_25c_w
    load_ratio = max_peak / inv_limit if inv_limit > 0 else 0

    # Zoek beter passend alternatief
    best_alt = None
    best_alt_reason = ""

    if load_ratio > ADVISOR_INV_OVERLOAD_PCT:
        label = ADVISOR_LABEL_UNDERPOWER
        score = max(0.0, 1.0 - (load_ratio - ADVISOR_INV_OVERLOAD_PCT) * 2)
        summary = (
            f"Piekbelasting {load_ratio*100:.0f}% van omvormerlimiet "
            f"({max_peak:.0f}W van {inv_limit:.0f}W). "
            f"Omvormer is aan de kleine kant."
        )
        # Zoek eerstvolgende grotere omvormer
        for alt_model, alt_inv in VICTRON_PROFILES.items():
            if alt_inv.power_cont_25c_w > inv_limit:
                new_ratio = max_peak / alt_inv.power_cont_25c_w
                if new_ratio < ADVISOR_INV_OVERLOAD_PCT:
                    best_alt = alt_model
                    best_alt_reason = (
                        f"Piekbelasting daalt naar {new_ratio*100:.0f}% "
                        f"van het nominale vermogen"
                    )
                    break

    elif load_ratio < ADVISOR_INV_UNDERLOAD_PCT:
        label = ADVISOR_LABEL_OVERSIZED
        score = max(0.0, 1.0 - (ADVISOR_INV_UNDERLOAD_PCT - load_ratio) * 2)
        summary = (
            f"Piekbelasting slechts {load_ratio*100:.0f}% van omvormerlimiet "
            f"({max_peak:.0f}W van {inv_limit:.0f}W). "
            f"Omvormer is overdimensioneerd."
        )
        # Zoek kleinere omvormer die nog net voldoet
        for alt_model, alt_inv in reversed(list(VICTRON_PROFILES.items())):
            if alt_inv.power_cont_25c_w < inv_limit:
                new_ratio = max_peak / alt_inv.power_cont_25c_w
                if new_ratio < ADVISOR_INV_OVERLOAD_PCT:
                    best_alt = alt_model
                    best_alt_reason = (
                        f"Volstaat voor gemeten pieken, lagere aanschafkosten"
                    )
                    break
    else:
        label = ADVISOR_LABEL_OPTIMAL
        score = 1.0 - abs(load_ratio - 0.55) * 0.5  # Ideaal ~55% belasting
        summary = (
            f"Omvormerbelasting {load_ratio*100:.0f}% — goed gedimensioneerd."
        )

    if not _should_update(state.prev_inverter_score, score, days):
        label = ADVISOR_LABEL_OPTIMAL if state.prev_inverter_score >= 0.6 else label

    return DimensionResult(
        label=label,
        score=score,
        summary=summary,
        alternative=best_alt,
        alternative_reason=best_alt_reason,
        days_of_data=days,
        confidence=_confidence(days),
        last_changed=state.inverter_changed,
    )


# ---------------------------------------------------------------------------
# Dimensie: Capaciteit
# ---------------------------------------------------------------------------

def _analyze_capacity(
    config: dict,
    coordinator_data: dict,
    days: float,
    state: AdvisorState,
) -> DimensionResult:
    """
    Analyseert dagelijkse records op leeglooppatronen en overcapaciteit.
    """
    records = state.daily_records
    if days < ADVISOR_MIN_DAYS or len(records) < 7:
        return DimensionResult(
            label=ADVISOR_LABEL_INSUFFICIENT_DATA, score=0.5,
            summary=f"Nog onvoldoende data ({days:.0f}/{ADVISOR_MIN_DAYS} dagen).",
            alternative=None, alternative_reason="",
            days_of_data=days, confidence=_confidence(days),
            last_changed=state.capacity_changed,
        )

    current_bat = config.get("battery_model", "US5000")
    modules = int(config.get("battery_modules", 1))
    current_cap = PYLONTECH_PROFILES[current_bat].usable_kwh * modules

    # Bereken ratio leeg-voor-23u en gemiddelde eind-SoC
    total = len(records)
    empty_before_23 = sum(1 for r in records if r.get("leeg_voor_23", False))
    avg_end_soc = sum(r.get("eind_soc", 50.0) for r in records) / total
    empty_ratio = empty_before_23 / total

    best_alt = None
    best_alt_reason = ""

    if empty_ratio > ADVISOR_CAP_EMPTY_PCT:
        label = ADVISOR_LABEL_TOO_SMALL
        score = max(0.0, 1.0 - (empty_ratio - ADVISOR_CAP_EMPTY_PCT) * 3)
        summary = (
            f"Batterij loopt op {empty_ratio*100:.0f}% van de dagen leeg vóór 23:00. "
            f"Huidige bruikbare capaciteit: {current_cap:.1f} kWh."
        )
        # Adviseer meer modules of groter model
        for bat_model, bat_profile in PYLONTECH_PROFILES.items():
            for n in range(modules + 1, min(modules + 4, 17)):
                alt_cap = bat_profile.usable_kwh * n
                if alt_cap > current_cap * 1.25:
                    best_alt = f"{n}× {bat_model}"
                    best_alt_reason = f"Bruikbare capaciteit {alt_cap:.1f} kWh (+{alt_cap-current_cap:.1f} kWh)"
                    break
            if best_alt:
                break

    elif avg_end_soc > ADVISOR_CAP_SURPLUS_SOC * 100:
        label = ADVISOR_LABEL_OVERSIZED
        score = max(0.0, 1.0 - (avg_end_soc/100 - ADVISOR_CAP_SURPLUS_SOC) * 2)
        summary = (
            f"Gemiddelde eind-SoC {avg_end_soc:.0f}% — mogelijk overcapaciteit. "
            f"Huidige bruikbare capaciteit: {current_cap:.1f} kWh."
        )
        # Adviseer minder modules
        if modules > 1:
            alt_modules = modules - 1
            alt_cap = PYLONTECH_PROFILES[current_bat].usable_kwh * alt_modules
            best_alt = f"{alt_modules}× {current_bat}"
            best_alt_reason = f"Bruikbare capaciteit {alt_cap:.1f} kWh, lagere investering"
    else:
        label = ADVISOR_LABEL_OPTIMAL
        score = 1.0 - abs(avg_end_soc/100 - 0.25) * 0.8  # Ideaal ~25% eind-SoC
        summary = (
            f"Capaciteit goed afgestemd op verbruik. "
            f"Gemiddelde eind-SoC: {avg_end_soc:.0f}%."
        )

    if not _should_update(state.prev_capacity_score, score, days):
        label = ADVISOR_LABEL_OPTIMAL if state.prev_capacity_score >= 0.6 else label

    return DimensionResult(
        label=label,
        score=score,
        summary=summary,
        alternative=best_alt,
        alternative_reason=best_alt_reason,
        days_of_data=days,
        confidence=_confidence(days),
        last_changed=state.capacity_changed,
    )


# ---------------------------------------------------------------------------
# Dimensie: Levensduur
# ---------------------------------------------------------------------------

def _analyze_lifetime(
    config: dict,
    coordinator_data: dict,
    days: float,
    state: AdvisorState,
) -> DimensionResult:
    """
    Analyseert gemiddelde DoD per cyclus en vergelijkt met gezond bereik.
    """
    cycles = coordinator_data.get("cycles", 0.0)
    energy_out = coordinator_data.get("energy_out", 0.0)

    current_bat = config.get("battery_model", "US5000")
    modules = int(config.get("battery_modules", 1))
    cap_kwh = PYLONTECH_PROFILES[current_bat].capacity_kwh * modules

    if days < ADVISOR_MIN_DAYS or cycles < 1.0:
        return DimensionResult(
            label=ADVISOR_LABEL_INSUFFICIENT_DATA, score=0.5,
            summary=f"Nog onvoldoende cyclusdata ({cycles:.1f} cycli).",
            alternative=None, alternative_reason="",
            days_of_data=days, confidence=_confidence(days),
            last_changed=state.lifetime_changed,
        )

    # Gemiddelde DoD per cyclus
    avg_dod = (energy_out / cycles) / cap_kwh if cap_kwh > 0 and cycles > 0 else 0.5

    best_alt = None
    best_alt_reason = ""

    if avg_dod > ADVISOR_DOD_HIGH_WEAR:
        label = ADVISOR_LABEL_HIGH_WEAR
        score = max(0.0, 1.0 - (avg_dod - ADVISOR_DOD_HEALTHY_MAX) * 2)
        summary = (
            f"Gemiddelde ontladingsdiepte {avg_dod*100:.0f}% — verhoogde slijtage. "
            f"Aanbevolen maximum: {ADVISOR_DOD_HEALTHY_MAX*100:.0f}%."
        )
        # Adviseer meer capaciteit voor ondiepe cycli
        if modules < 16:
            best_alt = f"{modules + 1}× {current_bat}"
            new_dod = avg_dod * (modules / (modules + 1))
            best_alt_reason = (
                f"Gemiddelde DoD daalt naar {new_dod*100:.0f}% — "
                f"langere batterijlevensduur"
            )

    elif avg_dod < ADVISOR_DOD_HEALTHY_MIN:
        label = ADVISOR_LABEL_UNDERUSED
        score = max(0.0, 1.0 - (ADVISOR_DOD_HEALTHY_MIN - avg_dod) * 2)
        summary = (
            f"Gemiddelde ontladingsdiepte slechts {avg_dod*100:.0f}% — "
            f"batterij wordt onderbenutt. "
            f"Gezond bereik: {ADVISOR_DOD_HEALTHY_MIN*100:.0f}–{ADVISOR_DOD_HEALTHY_MAX*100:.0f}%."
        )
        if modules > 1:
            best_alt = f"{modules - 1}× {current_bat}"
            new_dod = avg_dod * (modules / (modules - 1))
            best_alt_reason = (
                f"Gemiddelde DoD stijgt naar {new_dod*100:.0f}% — "
                f"beter capaciteitsgebruik"
            )
    else:
        label = ADVISOR_LABEL_HEALTHY
        score = 1.0 - abs(avg_dod - 0.55) * 0.5  # Ideaal ~55% DoD
        summary = (
            f"Ontladingspatroon gezond — gemiddelde DoD {avg_dod*100:.0f}%."
        )

    if not _should_update(state.prev_lifetime_score, score, days):
        label = ADVISOR_LABEL_HEALTHY if state.prev_lifetime_score >= 0.6 else label

    return DimensionResult(
        label=label,
        score=score,
        summary=summary,
        alternative=best_alt,
        alternative_reason=best_alt_reason,
        days_of_data=days,
        confidence=_confidence(days),
        last_changed=state.lifetime_changed,
    )


# ---------------------------------------------------------------------------
# Samenvatting
# ---------------------------------------------------------------------------

def _build_summary(
    financial: DimensionResult,
    inverter: DimensionResult,
    capacity: DimensionResult,
    lifetime: DimensionResult,
    config: dict,
) -> str:
    """
    Bouwt een menselijke samenvattende aanbeveling op basis van prioriteit:
    Financieel → Omvormer → Capaciteit → Levensduur.
    """
    bat_model = config.get("battery_model", "US5000")
    modules = int(config.get("battery_modules", 1))
    inv_model = config.get("inverter_model", "MultiPlus-II 48/5000")
    cap_kwh = PYLONTECH_PROFILES.get(bat_model,
        PYLONTECH_PROFILES["US5000"]).usable_kwh * modules

    system_desc = (
        f"{modules}× {bat_model} ({cap_kwh:.1f} kWh) "
        f"met {inv_model}"
    )

    # Onvoldoende data voor alle dimensies
    all_insufficient = all(
        r.label == ADVISOR_LABEL_INSUFFICIENT_DATA
        for r in [financial, inverter, capacity, lifetime]
    )
    if all_insufficient:
        days = financial.days_of_data
        return (
            f"Jouw systeem ({system_desc}) is actief en verzamelt data. "
            f"Na {ADVISOR_MIN_DAYS} dagen verschijnt hier een persoonlijk advies. "
            f"Voortgang: {days:.0f}/{ADVISOR_MIN_DAYS} dagen."
        )

    # Prioriteit: eerste niet-optimale dimensie bepaalt de samenvatting
    priority = [
        ("financieel", financial),
        ("omvormer", inverter),
        ("capaciteit", capacity),
        ("levensduur", lifetime),
    ]

    for dim_name, result in priority:
        if result.label in (
            ADVISOR_LABEL_INSUFFICIENT_DATA,
            ADVISOR_LABEL_OPTIMAL,
            ADVISOR_LABEL_HEALTHY,
        ):
            continue
        # Eerste niet-optimale dimensie gevonden
        alt_part = ""
        if result.alternative:
            alt_part = f" Overweeg: {result.alternative} ({result.alternative_reason})."
        return (
            f"Systeem: {system_desc}. "
            f"{result.summary}{alt_part} "
            f"[{result.confidence} betrouwbaarheid — {result.days_of_data:.0f} dagen data]"
        )

    # Alles optimaal
    return (
        f"Jouw systeem ({system_desc}) is goed geconfigureerd voor jouw "
        f"verbruikspatroon. Geen aanpassingen nodig op dit moment."
    )


# ---------------------------------------------------------------------------
# Hoofdfunctie — aanroepbaar vanuit de coordinator
# ---------------------------------------------------------------------------

def run_advisor(
    config: dict,
    coordinator_data: dict,
    state: AdvisorState,
) -> tuple[DimensionResult, DimensionResult, DimensionResult, DimensionResult, str]:
    """
    Voert alle vier dimensie-analyses uit en retourneert de resultaten plus
    de samenvattende tekst.

    Retourneert: (financial, inverter, capacity, lifetime, summary)
    """
    install_date = coordinator_data.get("install_date", "")
    days = _days_active(install_date)

    financial = _analyze_financial(config, coordinator_data, days, state)
    inverter   = _analyze_inverter(config, coordinator_data, days, state)
    capacity   = _analyze_capacity(config, coordinator_data, days, state)
    lifetime   = _analyze_lifetime(config, coordinator_data, days, state)
    summary    = _build_summary(financial, inverter, capacity, lifetime, config)

    # Bijwerken van de staat voor volgende run
    today = datetime.now().strftime("%Y-%m-%d")

    if _should_update(state.prev_financial_score, financial.score, days):
        state.prev_financial_score = financial.score
        state.financial_changed = today

    if _should_update(state.prev_inverter_score, inverter.score, days):
        state.prev_inverter_score = inverter.score
        state.inverter_changed = today

    if _should_update(state.prev_capacity_score, capacity.score, days):
        state.prev_capacity_score = capacity.score
        state.capacity_changed = today

    if _should_update(state.prev_lifetime_score, lifetime.score, days):
        state.prev_lifetime_score = lifetime.score
        state.lifetime_changed = today

    return financial, inverter, capacity, lifetime, summary
