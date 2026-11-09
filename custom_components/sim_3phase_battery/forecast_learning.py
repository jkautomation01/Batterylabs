"""
BatteryLabs 3-Phase -- Forecast Learning

Vergelijkt wat het systeem voor een uur voorspelde (PV-opwek, huisverbruik)
met wat er werkelijk gebeurde, en houdt per uur-van-de-dag een EMA-gladgestreken
correctiefactor bij. Deze factor wordt toegepast op toekomstige voorspellingen,
zodat systematische afwijkingen (bijv. panelen die 's ochtends structureel
minder opleveren dan het Gauss-model aanneemt) vanzelf worden gecorrigeerd
naarmate het systeem langer draait.

Werking, kort:
  1. Elk uur wordt de voorspelling die eerder voor dat uur werd vastgelegd
     opgehaald (staat te wachten in 'pending').
  2. Zodra het uur voorbij is, wordt de werkelijke waarde ernaast gelegd en
     wordt een ratio (werkelijk / voorspeld) berekend.
  3. Die ratio update een EMA per uur-van-de-dag (24 losse factoren per
     grootheid), begrensd zodat een enkele uitschieter de factor niet laat
     ontsporen.
  4. `apply_correction()` wordt door de planner aangeroepen om een ruwe
     voorspelling om te zetten in een gecorrigeerde voorspelling.

Alles is bewust eenvoudig en verklaarbaar (geen black-box model) zodat de
correctiefactor per uur uit te leggen is aan de gebruiker.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# EMA-snelheid voor de correctiefactoren zelf. Bewust trager dan het
# verbruiksprofiel (PROFILE_EMA_ALPHA) omdat een correctiefactor stabieler
# moet zijn -- die mag niet elke dag omslaan door één afwijkende meting.
CORRECTION_EMA_ALPHA = 0.08

# Begrenzing van de correctiefactor. Buiten dit bereik is de afwijking zo
# groot dat het waarschijnlijker een meetfout/eenmalige gebeurtenis is dan
# een structureel patroon -- de factor wordt dan niet verder bijgesteld.
FACTOR_MIN = 0.4
FACTOR_MAX = 1.8

# Minimum voorspelde waarde (W) om een ratio te berekenen. Onder deze
# drempel is de voorspelling zo dicht bij nul dat een ratio onbetrouwbaar
# wordt (kleine absolute afwijkingen geven enorme ratio's).
MIN_PREDICTION_W = 20.0


@dataclass
class ForecastLearningState:
    """Persistente staat: per uur-van-de-dag (0-23) een correctiefactor en
    diagnostische informatie, voor zowel PV als verbruik."""

    pv_factor: list = field(default_factory=lambda: [1.0] * 24)
    pv_samples: list = field(default_factory=lambda: [0] * 24)
    pv_last_error_pct: list = field(default_factory=lambda: [0.0] * 24)

    load_factor: list = field(default_factory=lambda: [1.0] * 24)
    load_samples: list = field(default_factory=lambda: [0] * 24)
    load_last_error_pct: list = field(default_factory=lambda: [0.0] * 24)

    # Wachtrij: voorspelling die is vastgelegd voor een uur, in afwachting
    # van de werkelijke waarde zodra dat uur voorbij is.
    # Sleutel: "YYYY-MM-DD-HH", waarde: {"pv_w": .., "load_w": ..}
    pending: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "pv_factor": self.pv_factor,
            "pv_samples": self.pv_samples,
            "pv_last_error_pct": self.pv_last_error_pct,
            "load_factor": self.load_factor,
            "load_samples": self.load_samples,
            "load_last_error_pct": self.load_last_error_pct,
            "pending": self.pending,
        }

    def from_dict(self, d: dict) -> None:
        if not d:
            return
        for attr in ("pv_factor", "pv_samples", "pv_last_error_pct",
                     "load_factor", "load_samples", "load_last_error_pct"):
            val = d.get(attr)
            if isinstance(val, list) and len(val) == 24:
                setattr(self, attr, val)
        pending = d.get("pending")
        if isinstance(pending, dict):
            self.pending = pending


def record_prediction(state: ForecastLearningState, key: str, pv_w: float, load_w: float) -> None:
    """Legt de voorspelling voor een specifiek uur vast (key = 'YYYY-MM-DD-HH')."""
    state.pending[key] = {"pv_w": pv_w, "load_w": load_w}
    # Voorkom onbeperkte groei: bewaar hooguit de laatste 72 uur aan pending
    # voorspellingen -- alles ouder dan dat is toch nooit meer vergeleken.
    if len(state.pending) > 72:
        oldest_keys = sorted(state.pending.keys())[: len(state.pending) - 72]
        for k in oldest_keys:
            state.pending.pop(k, None)


def _update_factor(factor_list: list, samples_list: list, error_list: list,
                    hour: int, predicted: float, actual: float) -> None:
    if predicted < MIN_PREDICTION_W:
        return
    ratio = actual / predicted
    ratio = max(0.1, min(3.0, ratio))  # extreme uitschieters afkappen vóór EMA

    old_factor = factor_list[hour]
    factor_list[hour] = (1 - CORRECTION_EMA_ALPHA) * old_factor + CORRECTION_EMA_ALPHA * ratio
    factor_list[hour] = max(FACTOR_MIN, min(FACTOR_MAX, factor_list[hour]))

    samples_list[hour] += 1
    error_pct = (ratio - 1.0) * 100
    error_list[hour] = round(error_pct, 1)


def evaluate_hour(state: ForecastLearningState, key: str, actual_pv_w: float, actual_load_w: float) -> bool:
    """
    Vergelijkt de eerder vastgelegde voorspelling voor 'key' met de
    werkelijke waarde, en werkt de correctiefactoren bij.
    Retourneert True als er een voorspelling was om mee te vergelijken.
    """
    entry = state.pending.pop(key, None)
    if entry is None:
        return False

    hour = int(key[-2:])
    _update_factor(state.pv_factor, state.pv_samples, state.pv_last_error_pct,
                    hour, entry["pv_w"], actual_pv_w)
    _update_factor(state.load_factor, state.load_samples, state.load_last_error_pct,
                    hour, entry["load_w"], actual_load_w)
    return True


def apply_pv_correction(state: ForecastLearningState, hour: int, raw_pv_w: float) -> float:
    """Past de geleerde correctiefactor toe op een ruwe PV-voorspelling."""
    return raw_pv_w * state.pv_factor[hour % 24]


def apply_load_correction(state: ForecastLearningState, hour: int, raw_load_w: float) -> float:
    """Past de geleerde correctiefactor toe op een ruwe verbruiksvoorspelling."""
    return raw_load_w * state.load_factor[hour % 24]


def summary_text(state: ForecastLearningState) -> str:
    """Mensleesbare samenvatting van de grootste structurele afwijkingen."""
    total_samples = sum(state.pv_samples) + sum(state.load_samples)
    if total_samples < 24:
        return "Nog aan het leren -- onvoldoende vergelijkingen tussen voorspelling en realiteit."

    pv_worst_hour = max(range(24), key=lambda h: abs(state.pv_factor[h] - 1.0))
    load_worst_hour = max(range(24), key=lambda h: abs(state.load_factor[h] - 1.0))

    parts = []
    pv_dev = (state.pv_factor[pv_worst_hour] - 1.0) * 100
    if abs(pv_dev) >= 8 and state.pv_samples[pv_worst_hour] >= 3:
        richting = "overschat" if pv_dev < 0 else "onderschat"
        parts.append(f"PV rond {pv_worst_hour:02d}:00 wordt {abs(pv_dev):.0f}% {richting}")

    load_dev = (state.load_factor[load_worst_hour] - 1.0) * 100
    if abs(load_dev) >= 8 and state.load_samples[load_worst_hour] >= 3:
        richting = "overschat" if load_dev < 0 else "onderschat"
        parts.append(f"verbruik rond {load_worst_hour:02d}:00 wordt {abs(load_dev):.0f}% {richting}")

    if not parts:
        return "Voorspellingen zijn goed gekalibreerd -- geen structurele afwijkingen gevonden."
    return "Geleerd: " + "; ".join(parts) + "."


def accuracy_pct(error_list: list, samples_list: list) -> float:
    """Gemiddelde nauwkeurigheid (100% = perfect) over uren met voldoende data."""
    errors = [abs(e) for e, s in zip(error_list, samples_list) if s >= 2]
    if not errors:
        return 0.0
    avg_error = sum(errors) / len(errors)
    return round(max(0.0, 100.0 - avg_error), 1)
