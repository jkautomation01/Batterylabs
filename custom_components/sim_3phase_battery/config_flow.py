"""
Config flow voor BatteryLabs 3-Phase.

Setup flow -- wizard, 4 stappen:
  user      -> P1 sensoren + temperatuursensor (optioneel)
  hardware  -> Batterij + omvormer + basisinstellingen
  energie   -> Prijssensor (optioneel) + vast tarief + terugleveringstarief
  zon       -> PV-forecast sensor (optioneel)

Dynamisch vs. vast tarief is geen keuze meer -- als er een prijssensor is
gekoppeld en die een forecast-attribuut heeft, wordt automatisch dynamisch
geoptimaliseerd; anders (of zodra de sensor geen geldige waarde geeft) valt
het systeem vanzelf terug op het ingevulde vaste tarief.

Options flow -- menu met losse secties:
  Kies welk onderdeel je wilt aanpassen, sla direct op.
  Extra menuoptie voor reset leerprofiel met bevestiging.
"""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import DOMAIN, FEED_IN_TARIFF_DEFAULT_EUR
from .hardware_profiles import PYLONTECH_PROFILES, VICTRON_PROFILES


# ---------------------------------------------------------------------------
# Schema-hulpfuncties
# ---------------------------------------------------------------------------

def _schema_sensors(defaults: dict) -> vol.Schema:
    """P1 sensoren (verplicht) en temperatuursensor (optioneel)."""
    return vol.Schema({
        vol.Required("l1_import_kw", default=defaults.get("l1_import_kw")): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor")),
        vol.Required("l1_export_kw", default=defaults.get("l1_export_kw")): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor")),
        vol.Required("l2_import_kw", default=defaults.get("l2_import_kw")): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor")),
        vol.Required("l2_export_kw", default=defaults.get("l2_export_kw")): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor")),
        vol.Required("l3_import_kw", default=defaults.get("l3_import_kw")): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor")),
        vol.Required("l3_export_kw", default=defaults.get("l3_export_kw")): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor")),
        vol.Optional("temp_sensor", default=defaults.get("temp_sensor", "")): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor")),
    })


def _schema_hardware(defaults: dict) -> vol.Schema:
    """Hardware selectie en basisinstellingen."""
    return vol.Schema({
        vol.Required("battery_model", default=defaults.get("battery_model", "US5000")): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=list(PYLONTECH_PROFILES.keys()),
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required("battery_modules", default=float(defaults.get("battery_modules", 1))): selector.NumberSelector(
            selector.NumberSelectorConfig(min=1, max=16, step=1, mode=selector.NumberSelectorMode.BOX)
        ),
        vol.Required("inverter_model", default=defaults.get("inverter_model", "MultiPlus-II 48/5000")): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=list(VICTRON_PROFILES.keys()),
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required("min_soc", default=float(defaults.get("min_soc", 10.0))): selector.NumberSelector(
            selector.NumberSelectorConfig(min=5, max=50, step=1, unit_of_measurement="%", mode=selector.NumberSelectorMode.SLIDER)
        ),
        vol.Optional("system_cost_euro", default=float(defaults.get("system_cost_euro", 0.0))): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=100000, step=500, unit_of_measurement="€", mode=selector.NumberSelectorMode.BOX)
        ),
    })


def _schema_energie(defaults: dict) -> vol.Schema:
    """Prijssensor (optioneel) + vast tarief + terugleveringstarief."""
    existing = defaults.get("zonneplan_sensor") or None
    return vol.Schema({
        vol.Optional("zonneplan_sensor", default=existing): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor")),
        vol.Required("fixed_price_eur", default=float(defaults.get("fixed_price_eur", 0.25))): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0.0, max=2.0, step=0.001, unit_of_measurement="€/kWh", mode=selector.NumberSelectorMode.BOX)
        ),
        vol.Required("feed_in_tariff_eur", default=float(defaults.get("feed_in_tariff_eur", FEED_IN_TARIFF_DEFAULT_EUR))): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0.0, max=1.0, step=0.001, unit_of_measurement="€/kWh", mode=selector.NumberSelectorMode.BOX)
        ),
    })


def _schema_zon(defaults: dict) -> vol.Schema:
    """PV-forecast sensor (optioneel)."""
    existing = defaults.get("solar_forecast_sensor") or None
    return vol.Schema({
        vol.Optional("solar_forecast_sensor", default=existing): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor")),
    })


def _schema_reset(defaults: dict) -> vol.Schema:
    """Bevestiging reset leerprofiel."""
    return vol.Schema({
        vol.Required("reset_profile_on_save", default=False): selector.BooleanSelector(),
    })


# ---------------------------------------------------------------------------
# Invoer verwerking
# ---------------------------------------------------------------------------

def _process_collected(data: dict) -> dict:
    """
    Verwerkt het gecombineerde data-dict na alle stappen.
    NumberSelector levert float -- integers worden expliciet omgezet.
    pv_present wordt afgeleid uit de PV-forecast sensor in plaats van een
    losse aan/uit-vraag: leeg = geen zonnepanelen.
    """
    processed = data.copy()
    processed["battery_modules"] = int(float(data.get("battery_modules", 1)))
    processed["min_soc"] = float(data.get("min_soc", 10.0))
    processed["system_cost_euro"] = float(data.get("system_cost_euro", 0.0))
    processed["fixed_price_eur"] = float(data.get("fixed_price_eur", 0.25))
    processed["feed_in_tariff_eur"] = float(data.get("feed_in_tariff_eur", FEED_IN_TARIFF_DEFAULT_EUR))

    processed.setdefault("temp_sensor", "")
    processed.setdefault("zonneplan_sensor", "")

    solar_sensor = processed.get("solar_forecast_sensor") or ""
    processed["solar_forecast_sensor"] = solar_sensor
    processed["pv_present"] = bool(solar_sensor)

    return processed


# ---------------------------------------------------------------------------
# Setup flow
# ---------------------------------------------------------------------------

class BatteryLabsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """
    Wizard-flow voor het aanmaken van een BatteryLabs integratie.
    Data wordt stap voor stap verzameld in self._data.
    """
    VERSION = 1

    def __init__(self):
        self._data: dict = {}

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_hardware()
        return self.async_show_form(
            step_id="user",
            data_schema=_schema_sensors(self._data),
            description_placeholders={"info": "Wijs de P1-sensoren aan van je slimme meter, één import én export per fase. Temperatuursensor is optioneel (standaard 20°C)."},
        )

    async def async_step_hardware(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_energie()
        return self.async_show_form(
            step_id="hardware",
            data_schema=_schema_hardware(self._data),
            description_placeholders={"info": "Kies de hardware die jouw installatie het best beschrijft. Systeemkostprijs is optioneel (0 = geen ROI-berekening)."},
        )

    async def async_step_energie(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_zon()
        return self.async_show_form(
            step_id="energie",
            data_schema=_schema_energie(self._data),
            description_placeholders={"info": "Prijssensor is optioneel -- heeft hij een uurprijzen-forecast, dan optimaliseert het systeem daarop; anders (of zonder sensor) gebruikt het altijd het vaste tarief."},
        )

    async def async_step_zon(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return self._create_entry()
        return self.async_show_form(
            step_id="zon",
            data_schema=_schema_zon(self._data),
            description_placeholders={"info": "Heb je zonnepanelen? Wijs de forecast.solar sensor aan met de verwachte dagproductie. Laat leeg als je geen PV hebt."},
        )

    def _create_entry(self):
        try:
            processed = _process_collected(self._data)
            return self.async_create_entry(title="BatteryLabs Systeem", data=processed)
        except Exception:
            return self.async_abort(reason="invalid_config")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return BatteryLabsOptionsFlowHandler()


# ---------------------------------------------------------------------------
# Options flow -- menu-gebaseerd
# ---------------------------------------------------------------------------

class BatteryLabsOptionsFlowHandler(config_entries.OptionsFlow):
    """
    Options flow met een menu als startpunt.
    Elke sectie heeft eigen unieke step-IDs (prefix 'opt_') om conflicten
    met de setup flow te vermijden.
    Wijzigingen worden direct opgeslagen zodra een sectie wordt bevestigd.
    """

    def __init__(self):
        # config_entry wordt automatisch gezet door HA -- niet zelf setten.
        # _data initialiseren we in async_step_init zodra config_entry beschikbaar is.
        self._data: dict = {}

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    async def async_step_init(self, user_input=None):
        """
        Startpunt: toon een menu met alle aanpasbare secties.
        async_show_menu is de HA-native manier voor keuzemenus in flows.
        """
        # config_entry is nu beschikbaar via de basisklasse -- laad de huidige config
        if not self._data:
            self._data = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_menu(
            step_id="init",
            menu_options={
                "opt_sensors":  "🔌  Sensoren",
                "opt_hardware": "⚙️  Hardware",
                "opt_energie":  "💶  Energie & prijs",
                "opt_zon":      "☀️  Zonnepanelen",
                "opt_reset":    "🔄  Reset leerprofiel",
            },
        )

    # ------------------------------------------------------------------
    # Sectie: Sensoren
    # ------------------------------------------------------------------

    async def async_step_opt_sensors(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self._save()
        return self.async_show_form(
            step_id="opt_sensors",
            data_schema=_schema_sensors(self._data),
            description_placeholders={"info": "Pas de P1-sensoren of de temperatuursensor aan."},
        )

    # ------------------------------------------------------------------
    # Sectie: Hardware
    # ------------------------------------------------------------------

    async def async_step_opt_hardware(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self._save()
        return self.async_show_form(
            step_id="opt_hardware",
            data_schema=_schema_hardware(self._data),
            description_placeholders={"info": "Wijzig het batterij- of omvormermodel, SoC-grens of systeemkostprijs."},
        )

    # ------------------------------------------------------------------
    # Sectie: Energie & prijs
    # ------------------------------------------------------------------

    async def async_step_opt_energie(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self._save()
        return self.async_show_form(
            step_id="opt_energie",
            data_schema=_schema_energie(self._data),
            description_placeholders={"info": "Prijssensor is optioneel -- met forecast-attribuut wordt dynamisch geoptimaliseerd, anders geldt altijd het vaste tarief."},
        )

    # ------------------------------------------------------------------
    # Sectie: Zonnepanelen
    # ------------------------------------------------------------------

    async def async_step_opt_zon(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self._save()
        return self.async_show_form(
            step_id="opt_zon",
            data_schema=_schema_zon(self._data),
            description_placeholders={"info": "Wijs de forecast.solar sensor aan, of laat leeg om PV uit te schakelen."},
        )

    # ------------------------------------------------------------------
    # Sectie: Reset leerprofiel
    # ------------------------------------------------------------------

    async def async_step_opt_reset(self, user_input=None):
        if user_input is not None:
            should_reset = bool(user_input.get("reset_profile_on_save", False))
            if should_reset:
                coordinator = self.hass.data.get(DOMAIN, {}).get(
                    self.config_entry.entry_id
                )
                if coordinator is not None:
                    await coordinator.async_reset_profile()
            # Reset slaat geen config op -- terug naar menu via lege entry
            return self.async_create_entry(title="", data={})
        return self.async_show_form(
            step_id="opt_reset",
            data_schema=_schema_reset(self._data),
            description_placeholders={
                "info": (
                    "Wis het leerproces volledig. Besparing, cycli en "
                    "batterijgezondheid blijven bewaard. Het systeem valt "
                    "terug op eenvoudige regels totdat er nieuwe profieldata is."
                )
            },
        )

    # ------------------------------------------------------------------
    # Opslaan
    # ------------------------------------------------------------------

    async def _save(self):
        """Verwerk _data en sla het op als entry.options.

        De coordinator leest {**entry.data, **entry.options}, dus opties
        overschrijven de oorspronkelijke setup-data. De update-listener in
        __init__ herlaadt de integratie zodat wijzigingen direct actief worden.
        """
        try:
            processed = _process_collected(self._data)
        except Exception:
            return self.async_abort(reason="invalid_config")

        return self.async_create_entry(title="", data=processed)
