"""Constants voor de BatteryLabs 3-Phase integratie."""

DOMAIN = "sim_3phase_battery"

# ---------------------------------------------------------------------------
# Persistentie
# ---------------------------------------------------------------------------
SAVE_INTERVAL_S = 600               # Seconden tussen state-saves
PROFILE_SAVE_INTERVAL_S = 1800      # Seconden tussen profiel-saves (30 min)

# ---------------------------------------------------------------------------
# Leerproces drempelwaarden
# ---------------------------------------------------------------------------
PROFILE_SLOTS_TOTAL = 168           # 7 dagen × 24 uur

# Unieke kalenderdagen per slot voor drempelwaarden
PROFILE_THRESHOLD_ACTIVE = 14       # 2 weken
PROFILE_THRESHOLD_RELIABLE = 28     # 4 weken

PROFILE_WEEKS_ACTIVE = 2
PROFILE_WEEKS_RELIABLE = 4
# Max bewaarde unieke dagen per slot — begrenst groei van het profiel-JSON
PROFILE_DAYS_CAP = 35

# EMA-smoothingsfactor voor profielupdate
PROFILE_EMA_ALPHA = 0.1

# ---------------------------------------------------------------------------
# Prijsclassificatie (Zonneplan forecast)
# ---------------------------------------------------------------------------
ZONNEPLAN_PRICE_DIVISOR = 10_000_000  # millionths van euro per kWh

PRICE_PERCENTILE_CHEAP = 30
PRICE_PERCENTILE_EXPENSIVE = 70
PRICE_NEGATIVE_THRESHOLD = 0.0

# Spread-arbitrage: verschil tussen duurste en goedkoopste uur van de dag.
# Onder de drempel is arbitrage de cyclus-slijtage niet waard -> vasthouden.
# Boven de drempel schaalt de laad/ontlaaddiepte mee tot de max-spread,
# waarna volledige diepte (25%) wordt toegepast.
PRICE_SPREAD_MIN_EUR = 0.08          # Onder dit verschil: geen arbitrage
PRICE_SPREAD_MAX_EUR = 0.30          # Vanaf dit verschil: volledige diepte
PRICE_SPREAD_MAX_DEPTH_PCT = 25.0    # Max SoC-verandering per uur bij volledige diepte

# Terugleveringstarief: verrekent PV-overschot dat de batterij niet opvangt.
# Nodig zodra saldering wegvalt en export minder oplevert dan afname kost.
FEED_IN_MODE_FIXED = "fixed"
FEED_IN_MODE_SENSOR = "sensor"
FEED_IN_TARIFF_DEFAULT_EUR = 0.00

# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------
OPTIMIZER_SOC_BUFFER_PCT = 5.0
OPTIMIZER_PLAN_HORIZON_H = 24
OPTIMIZER_SOLAR_SURPLUS_THRESHOLD_W = 200.0

SOLAR_GAUSS_PEAK_HOUR = 13.0
SOLAR_GAUSS_SIGMA = 3.0

# ---------------------------------------------------------------------------
# Hardware limieten
# ---------------------------------------------------------------------------
DC_VOLTAGE_MIN = 44.5
POWER_ACTIVE_THRESHOLD_W = 5.0
INV_THERMAL_RESISTANCE = 110.0

# ---------------------------------------------------------------------------
# Degradatie & Health
# ---------------------------------------------------------------------------
SOH_WARNING_THRESHOLD = 80.0
TEMP_BAT_WARNING_HIGH = 45.0
TEMP_BAT_CAUTION_LOW = 5.0

# ---------------------------------------------------------------------------
# Modi
# ---------------------------------------------------------------------------
MODE_ECO = "Eco (Zelfverbruik)"
MODE_SMART = "Smart (Dynamic)"
MODE_FORCE = "Full Charge (Force)"
MODE_SMART_PRO = "Smart Pro (Predictief)"
ALL_MODES = [MODE_ECO, MODE_SMART, MODE_FORCE, MODE_SMART_PRO]

# ---------------------------------------------------------------------------
# Voortgangsstatus labels
# ---------------------------------------------------------------------------
PROFILE_STATUS_LEARNING = "Leren"
PROFILE_STATUS_ACTIVE_LIMITED = "Actief (beperkte data)"
PROFILE_STATUS_ACTIVE_RELIABLE = "Actief (betrouwbaar)"

# ---------------------------------------------------------------------------
# Contracttype
# ---------------------------------------------------------------------------
CONTRACT_DYNAMIC = "Dynamisch (Zonneplan)"
CONTRACT_FIXED = "Vast tarief"
CONTRACT_TYPES = [CONTRACT_DYNAMIC, CONTRACT_FIXED]

# Standaard tijdsblokken voor vast contract — (start_uur, eind_uur, classificatie)
# Classificaties: "cheap", "normal", "expensive"
FIXED_CONTRACT_TIME_BLOCKS_DEFAULT = [
    (0,  7,  "cheap"),      # Nacht: laag netverbruik
    (7,  9,  "expensive"),  # Ochtendpiek: ontbijt, douche, vertrek
    (9,  16, "normal"),     # Dag: PV-periode, normaal verbruik
    (16, 23, "expensive"),  # Avondpiek: koken, entertainment, laden auto
    (23, 24, "cheap"),      # Late nacht: laag verbruik
]

# ---------------------------------------------------------------------------
# EV-bewustzijn
# ---------------------------------------------------------------------------
EV_MIN_SOC_DEFAULT = 40.0           # % — default reserve tijdens EV-laden

# ---------------------------------------------------------------------------
# Systeemaanbeveling — drempelwaarden
# ---------------------------------------------------------------------------
ADVISOR_MIN_DAYS = 14               # Dagen data voor eerste advies

# Stabiliteitsdrempels: minimale score-afwijking voor advieswijziging
ADVISOR_STABILITY_14D  = 0.30       # < 30 dagen: 30% afwijking nodig
ADVISOR_STABILITY_30D  = 0.20       # 30–90 dagen: 20% afwijking nodig
ADVISOR_STABILITY_90D  = 0.15       # 90+ dagen: 15% afwijking nodig

# Omvormer dimensionering
ADVISOR_INV_OVERLOAD_PCT   = 0.85   # >85% van limiet = ondervermogen
ADVISOR_INV_UNDERLOAD_PCT  = 0.25   # <25% van limiet = overdimensioneerd

# Capaciteit
ADVISOR_CAP_EMPTY_PCT      = 0.20   # >20% van dagen leeg vóór 23:00 = te klein
ADVISOR_CAP_SURPLUS_SOC    = 0.50   # Gemiddelde eind-SoC >50% = overcapaciteit

# Levensduur (DoD-patronen)
ADVISOR_DOD_HEALTHY_MIN    = 0.40   # DoD < 40% = onderbenutt
ADVISOR_DOD_HEALTHY_MAX    = 0.70   # DoD > 70% = verhoogde slijtage
ADVISOR_DOD_HIGH_WEAR      = 0.80   # DoD > 80% = hoge slijtage

# Advies labels
ADVISOR_LABEL_OPTIMAL      = "Optimaal"
ADVISOR_LABEL_TOO_SMALL    = "Te klein"
ADVISOR_LABEL_OVERSIZED    = "Overdimensioneerd"
ADVISOR_LABEL_UNDERPOWER   = "Ondervermogen"
ADVISOR_LABEL_HEALTHY      = "Gezond"
ADVISOR_LABEL_HIGH_WEAR    = "Hoge slijtage"
ADVISOR_LABEL_UNDERUSED    = "Onderbenutt"
ADVISOR_LABEL_ALT_AVAILABLE = "Alternatief beschikbaar"
ADVISOR_LABEL_INSUFFICIENT_DATA = "Onvoldoende data"
