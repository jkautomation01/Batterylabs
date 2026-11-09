"""
BatteryLabs 3-Phase -- DP Optimizer

Vervangt de greedy prioriteitsketen-heuristiek in _build_plan() door een
exact-optimale dynamic-programming-oplossing over de volledige forecast-
horizon (typisch 24-96 stappen, afhankelijk van de brondata-resolutie).

Waarom DP i.p.v. LP/scipy: scipy is niet beschikbaar op een standaard HAOS-
installatie. DP is hier bovendien geschikter dan lineair programmeren omdat
de SoC-grenzen natuurlijke discrete constraints zijn en de actieruimte
(laad/ontlaad-vermogen) toch al gediscretiseerd wordt.

Toestandsruimte: (stap, SoC-niveau). Voor elke toestand wordt achterwaarts
(van het einde van de horizon terug naar nu) de minimale totale netkosten
berekend, en de bijbehorende optimale actie opgeslagen. Dit garandeert een
global optimum binnen de gekozen resolutie.

Slijtagekosten i.p.v. een hard cyclusbudget: elke ontlaadactie krijgt een
economische slijtagekost (wear_coeff_eur * dod_fractie^2) die de aanroeper
afleidt uit de daadwerkelijke batterij-vervangingswaarde en cycluslevensduur
(zie BatteryCoordinator._build_plan_dp). Zo cyclet de optimizer vanzelf
minder bij kleine prijsspreads en meer bij grote -- zonder een handmatig
geplafonneerd cyclusbudget. Dit elimineert ook de budget-dimensie uit de
toestandsruimte, wat de DP flink versnelt (minder dimensies om te doorzoeken).

Tijdresolutie: prices_eur mag zowel uur- als kwartierdata bevatten. De
step_hours-parameter geeft aan hoeveel klokuren 1 stap beslaat (1.0 =
uurprijzen, 0.25 = kwartierprijzen). house_load_kwh en pv_surplus_kwh moeten
door de aanroeper al geschaald zijn naar energie per stap.
"""
from __future__ import annotations

import time
import logging
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)

INF = float("inf")


@dataclass
class DPResult:
    """Een regel van de geoptimaliseerde planning voor een specifieke stap."""
    hour_offset: int
    price_eur: float
    action_kwh: float
    target_soc: float
    sustainability_score: float


def _states(lo: float, hi: float, step: float) -> list:
    n = max(1, int(round((hi - lo) / step)) + 1)
    return [lo + i * step for i in range(n)]


def _snap(value: float, lo: float, step: float, n: int) -> int:
    idx = round((value - lo) / step)
    return max(0, min(n - 1, idx))


def solve(
    prices_eur, house_load_kwh, sustainability, start_soc, cap_kwh, eta,
    max_power_kw, min_soc, max_soc, wear_coeff_eur=0.0, pv_surplus_kwh=None,
    feed_in_price_eur=0.0, sustainability_weight=0.0, soc_step=1.0, action_step_kw=1.0,
    step_hours=1.0,
):
    """
    Lost de optimale laad/ontlaad-planning op over len(prices_eur) stappen.

    wear_coeff_eur: slijtagekost in euro voor één volledige cyclus (dod=1.0)
    van het hele batterijpakket. De kost voor een actie schaalt kwadratisch
    met de ontladingsdiepte van die stap (wear_coeff_eur * dod^2), passend
    bij het degradatiemodel in hardware_profiles.PylontechProfile.

    sustainability_weight: 0.0 = puur financieel optimaliseren, > 0 geeft een
    kleine kostenkorting bij hogere sustainability_score, als tie-breaker
    tussen anders vergelijkbare stappen (nooit dominant over de prijs zelf).

    step_hours: duur van 1 stap in prices_eur, in klokuren (1.0 = uurprijzen,
    0.25 = kwartierprijzen).

    Retourneert (planning, verwachte_totale_kosten_eur).
    """
    t_start = time.monotonic()
    n_hours = len(prices_eur)
    if n_hours == 0:
        return [], 0.0

    soc_states = _states(min_soc, max_soc, soc_step)
    n_soc = len(soc_states)

    actions_kw = [
        i * action_step_kw
        for i in range(int(-max_power_kw / action_step_kw), int(max_power_kw / action_step_kw) + 1)
    ]

    value = [[INF] * n_soc for _ in range(n_hours + 1)]
    policy = [[0.0] * n_soc for _ in range(n_hours)]
    for si in range(n_soc):
        value[n_hours][si] = 0.0

    max_sust = max(sustainability) if sustainability and max(sustainability) > 0 else 1.0

    for h in range(n_hours - 1, -1, -1):
        price = prices_eur[h]
        load_kwh = house_load_kwh[h] if h < len(house_load_kwh) else 0.3 * step_hours
        sust = (sustainability[h] / max_sust) if h < len(sustainability) else 0.0
        surplus_kwh = pv_surplus_kwh[h] if pv_surplus_kwh and h < len(pv_surplus_kwh) else 0.0
        effective_price = price * (1.0 - sustainability_weight * sust)

        for si, soc in enumerate(soc_states):
            best_cost = INF
            best_action = 0.0
            for action_kw in actions_kw:
                action_kwh = action_kw * step_hours

                if action_kwh > 0:
                    new_soc = soc + (action_kwh * eta / cap_kwh) * 100
                    grid_extra = action_kwh / eta
                else:
                    new_soc = soc + (action_kwh / eta / cap_kwh) * 100
                    grid_extra = action_kwh * eta

                if new_soc < min_soc - 1e-6 or new_soc > max_soc + 1e-6:
                    continue

                new_si = _snap(new_soc, min_soc, soc_step, n_soc)

                house_net_kwh = load_kwh + grid_extra
                unabsorbed_surplus = max(0.0, surplus_kwh - max(0.0, action_kwh))
                step_cost = house_net_kwh * effective_price
                step_cost += unabsorbed_surplus * max(0.0, effective_price - feed_in_price_eur)
                if action_kwh < 0:
                    dod_fraction = abs(action_kwh) / cap_kwh
                    step_cost += wear_coeff_eur * dod_fraction ** 2

                future_cost = value[h + 1][new_si]
                if future_cost == INF:
                    continue
                total = step_cost + future_cost
                if total < best_cost:
                    best_cost = total
                    best_action = action_kwh

            value[h][si] = best_cost
            policy[h][si] = best_action

    soc = start_soc
    total_cost = 0.0
    results = []

    for h in range(n_hours):
        si = _snap(soc, min_soc, soc_step, n_soc)
        action_kwh = policy[h][si]

        price = prices_eur[h]
        load_kwh = house_load_kwh[h] if h < len(house_load_kwh) else 0.3 * step_hours
        sust = sustainability[h] if h < len(sustainability) else 0.0

        if action_kwh > 0:
            new_soc = soc + (action_kwh * eta / cap_kwh) * 100
            grid_extra = action_kwh / eta
        else:
            new_soc = soc + (action_kwh / eta / cap_kwh) * 100
            grid_extra = action_kwh * eta
        new_soc = max(min_soc, min(max_soc, new_soc))

        total_cost += (load_kwh + grid_extra) * price
        surplus_kwh_fwd = pv_surplus_kwh[h] if pv_surplus_kwh and h < len(pv_surplus_kwh) else 0.0
        unabsorbed_fwd = max(0.0, surplus_kwh_fwd - max(0.0, action_kwh))
        total_cost += unabsorbed_fwd * max(0.0, price - feed_in_price_eur)
        soc = new_soc

        results.append(DPResult(
            hour_offset=h, price_eur=price, action_kwh=action_kwh,
            target_soc=round(soc, 1), sustainability_score=sust,
        ))

    elapsed = time.monotonic() - t_start
    _LOGGER.info(
        "BatteryLabs DP-optimizer: %d stappen (%.2fu elk), %d SoC-niveaus, "
        "%.2fs, verwachte kosten EUR %.4f", n_hours, step_hours, n_soc, elapsed, total_cost,
    )
    return results, total_cost
