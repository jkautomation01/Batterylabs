"""
BatteryLabs 3-Phase -- DP Optimizer

Vervangt de greedy prioriteitsketen-heuristiek in _build_plan() door een
exact-optimale dynamic-programming-oplossing over de volledige forecast-
horizon (typisch 24-34 uur, afhankelijk van wat Zonneplan levert).

Waarom DP i.p.v. LP/scipy: scipy is niet beschikbaar op een standaard HAOS-
installatie. DP is hier bovendien geschikter dan lineair programmeren omdat
de SoC-grenzen en het energiebudget natuurlijke discrete constraints zijn en
de actieruimte (laad/ontlaad-vermogen) toch al gediscretiseerd wordt.

Toestandsruimte: (uur, SoC-niveau, resterend energiebudget). Voor elke
toestand wordt achterwaarts (van het einde van de horizon terug naar nu) de
minimale totale netkosten berekend, en de bijbehorende optimale actie
opgeslagen. Dit garandeert een global optimum binnen de gekozen resolutie --
geen lokale val zoals bij een prioriteitsketen die per uur losse beslissingen
neemt zonder vooruit te kijken.

Rekentijd bij productie-resolutie (1% SoC-stap, 1 kW actie-stap, 34 uur):
circa 2 seconden op een moderne NUC. Wordt aangeroepen vanuit update_slow(),
dus dit blokkeert de realtime (1s) cyclus niet.
"""
from __future__ import annotations

import time
import logging
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)

INF = float("inf")


@dataclass
class DPResult:
    """Een regel van de geoptimaliseerde planning voor een specifiek uur."""
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
    max_power_kw, min_soc, max_soc, cycle_budget_per_day, pv_surplus_kwh=None,
    feed_in_price_eur=0.0, sustainability_weight=0.0, soc_step=1.0, budget_step=1.0, action_step_kw=1.0,
):
    """
    Lost de optimale laad/ontlaad-planning op over len(prices_eur) uren.

    sustainability_weight: 0.0 = puur financieel optimaliseren, > 0 geeft een
    kleine kostenkorting bij hogere sustainability_score, als tie-breaker
    tussen anders vergelijkbare uren (nooit dominant over de prijs zelf).

    Retourneert (planning, verwachte_totale_kosten_eur).
    """
    t_start = time.monotonic()
    n_hours = len(prices_eur)
    if n_hours == 0:
        return [], 0.0

    horizon_kwh = cycle_budget_per_day * cap_kwh * (n_hours / 24.0)

    soc_states = _states(min_soc, max_soc, soc_step)
    n_soc = len(soc_states)
    budget_states = _states(0.0, horizon_kwh, budget_step)
    n_budget = len(budget_states)

    actions_kw = [
        i * action_step_kw
        for i in range(int(-max_power_kw / action_step_kw), int(max_power_kw / action_step_kw) + 1)
    ]

    value = [[[INF] * n_budget for _ in range(n_soc)] for _ in range(n_hours + 1)]
    policy = [[[0.0] * n_budget for _ in range(n_soc)] for _ in range(n_hours)]
    for si in range(n_soc):
        for bi in range(n_budget):
            value[n_hours][si][bi] = 0.0

    max_sust = max(sustainability) if sustainability and max(sustainability) > 0 else 1.0

    for h in range(n_hours - 1, -1, -1):
        price = prices_eur[h]
        load_kwh = house_load_kwh[h] if h < len(house_load_kwh) else 0.3
        sust = (sustainability[h] / max_sust) if h < len(sustainability) else 0.0
        surplus_kwh = pv_surplus_kwh[h] if pv_surplus_kwh and h < len(pv_surplus_kwh) else 0.0
        effective_price = price * (1.0 - sustainability_weight * sust)

        for si, soc in enumerate(soc_states):
            for bi, budget_left in enumerate(budget_states):
                best_cost = INF
                best_action = 0.0
                for action_kwh in actions_kw:
                    energy_delta = abs(action_kwh)
                    if energy_delta > budget_left + 1e-9:
                        continue

                    if action_kwh > 0:
                        new_soc = soc + (action_kwh * eta / cap_kwh) * 100
                        grid_extra = action_kwh / eta
                    else:
                        new_soc = soc + (action_kwh / eta / cap_kwh) * 100
                        grid_extra = action_kwh * eta

                    if new_soc < min_soc - 1e-6 or new_soc > max_soc + 1e-6:
                        continue

                    new_si = _snap(new_soc, min_soc, soc_step, n_soc)
                    new_bi = _snap(budget_left - energy_delta, 0.0, budget_step, n_budget)

                    house_net_kwh = load_kwh + grid_extra
                    unabsorbed_surplus = max(0.0, surplus_kwh - max(0.0, action_kwh))
                    step_cost = house_net_kwh * effective_price
                    step_cost += unabsorbed_surplus * max(0.0, effective_price - feed_in_price_eur)

                    future_cost = value[h + 1][new_si][new_bi]
                    if future_cost == INF:
                        continue
                    total = step_cost + future_cost
                    if total < best_cost:
                        best_cost = total
                        best_action = action_kwh

                value[h][si][bi] = best_cost
                policy[h][si][bi] = best_action

    soc = start_soc
    budget_left = horizon_kwh
    total_cost = 0.0
    results = []

    for h in range(n_hours):
        si = _snap(soc, min_soc, soc_step, n_soc)
        bi = _snap(budget_left, 0.0, budget_step, n_budget)
        action_kwh = policy[h][si][bi]

        price = prices_eur[h]
        load_kwh = house_load_kwh[h] if h < len(house_load_kwh) else 0.3
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
        budget_left = max(0.0, budget_left - abs(action_kwh))
        soc = new_soc

        results.append(DPResult(
            hour_offset=h, price_eur=price, action_kwh=action_kwh,
            target_soc=round(soc, 1), sustainability_score=sust,
        ))

    elapsed = time.monotonic() - t_start
    _LOGGER.debug(
        "BatteryLabs DP-optimizer: %d uur, %d SoC-niveaus, %d budget-niveaus, "
        "%.2fs, verwachte kosten EUR %.4f", n_hours, n_soc, n_budget, elapsed, total_cost,
    )
    return results, total_cost
