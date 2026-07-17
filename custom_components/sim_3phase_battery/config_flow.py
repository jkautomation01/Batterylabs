"""
Config flow voor BatteryLabs 3-Phase.

Setup flow -- wizard, 6 stappen:
  user       -> P1 sensoren + temperatuursensor
  hardware   -> Batterij + omvormer + basisinstellingen
  contract   -> Contracttype
  pricing    -> Prijs (dynamisch of vast, afhankelijk van contract)
  feed_in    -> Terugleveringstarief (vast of sensor)
  feed_in_detail -> Details afhankelijk van gekozen modus
  pv_choice  -> PV aanwezig?
  pv_sensor  -> Forecast sensor (alleen als pv_present=True)

Options flow -- menu met losse secties:
  Kies welk onderdeel je wilt aanpassen, sla direct op.
  Extra menuoptie voor reset leerprofiel met bevestiging.
"""
import json as _json
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONTRACT_DYNAMIC, CONTRACT_FIXED, CONTRACT_TYPES,
    EV_MIN_SOC_DEFAULT,
    FEED_IN_MODE_FIXED, FEED_IN_MODE_SENSOR, FEED_IN_TARIFF_DEFAULT_EUR,
)
from .hardware_profiles import PYLONTECH_PROFILES, VICTRON_PROFILES


# ---------------------------------------------------------------------------
# Schema-hulpfuncties
# ---------------------------------------------------------------------------

def _schema_sensors(defaults: dict) -> vol.Schema:
    """P1 sensoren en temperatuursensor."""
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
        vol.Required("temp_sensor", default=defaults.get("temp_sensor")): selector.EntitySelector(
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
        vol.Required("update_interval", default=float(defaults.get("update_interval", 5))): selector.NumberSelector(
            selector.NumberSelectorConfig(min=5, max=60, step=5, unit_of_measurement="s", mode=selector.NumberSelectorMode.SLIDER)
        ),
        vol.Required("system_cost_euro", default=float(defaults.get("system_cost_euro", 15000))): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=100000, step=500, unit_of_measurement="€", mode=selector.NumberSelectorMode.BOX)
        ),
    })


def _schema_contract(defaults: dict) -> vol.Schema:
    """Contracttype kiezen."""
    return vol.Schema({
        vol.Required("contract_type", default=defaults.get("contract_type", CONTRACT_DYNAMIC)): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=CONTRACT_TYPES,
                mode=selector.SelectSelectorMode.LIST,
            )
        ),
    })


def _schema_pricing_dynamic(defaults: dict) -> vol.Schema:
    """Dynamisch contract: prijssensor + Zonneplan."""
    return vol.Schema({
        vol.Required("price_sensor", default=defaults.get("price_sensor", "")): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor")),
        vol.Optional("zonneplan_sensor", default=defaults.get("zonneplan_sensor", "")): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor")),
    })


def _schema_pricing_fixed(defaults: dict) -> vol.Schema:
    """Vast contract: vaste prijs + optionele sensor + tijdsblokken."""
    return vol.Schema({
        vol.Required("fixed_price_eur", default=float(defaults.get("fixed_price_eur", 0.25))): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0.0, max=2.0, step=0.001, unit_of_measurement="€/kWh", mode=selector.NumberSelectorMode.BOX)
        ),
        vol.Optional("price_sensor", default=defaults.get("price_sensor", "")): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor")),
        vol.Optional("fixed_time_blocks", default=defaults.get("fixed_time_blocks", "")): selector.TextSelector(
            selector.TextSelectorConfig(multiline=False)
        ),
    })


def _schema_feed_in_mode(defaults: dict) -> vol.Schema:
    """Kies: vast getal of gekoppeld aan een sensor."""
    return vol.Schema({
        vol.Required("feed_in_mode", default=defaults.get("feed_in_mode", FEED_IN_MODE_FIXED)): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[FEED_IN_MODE_FIXED, FEED_IN_MODE_SENSOR],
                mode=selector.SelectSelectorMode.LIST,
            )
        ),
    })


def _schema_feed_in_fixed(defaults: dict) -> vol.Schema:
    """Vast terugleveringstarief in euro per kWh."""
    return vol.Schema({
        vol.Required("feed_in_tariff_eur", default=float(defaults.get("feed_in_tariff_eur", FEED_IN_TARIFF_DEFAULT_EUR))): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0.0, max=1.0, step=0.001, unit_of_measurement="€/kWh", mode=selector.NumberSelectorMode.BOX)
        ),
    })


def _schema_feed_in_sensor(defaults: dict) -> vol.Schema:
    """Terugleveringstarief gekoppeld aan een sensor."""
    existing = defaults.get("feed_in_tariff_sensor") or None
    return vol.Schema({
        vol.Required("feed_in_tariff_sensor", default=existing): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor")),
    })


def _schema_pv_choice(defaults: dict) -> vol.Schema:
    """PV aanwezig?"""
    return vol.Schema({
        vol.Required("pv_present", default=bool(defaults.get("pv_present", False))): selector.BooleanSelector(),
    })


def _schema_pv_sensor(defaults: dict) -> vol.Schema:
    """Forecast.solar sensor."""
    existing = defaults.get("solar_forecast_sensor") or None
    return vol.Schema({
        vol.Required("solar_forecast_sensor", default=existing): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor")),
    })


def _schema_reset(defaults: dict) -> vol.Schema:
    """Bevestiging reset leerprofiel."""
    return vol.Schema({
        vol.Required("reset_profile_on_save", default=False): selector.BooleanSelector(),
    })


def _schema_ev(defaults: dict) -> vol.Schema:
    """EV-laadstatus sensor en reserve SoC."""
    return vol.Schema({
        vol.Optional("ev_charging_sensor", default=defaults.get("ev_charging_sensor", "")): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="binary_sensor")),
        vol.Optional("ev_min_soc", default=float(defaults.get("ev_min_soc", EV_MIN_SOC_DEFAULT))): selector.NumberSelector(
            selector.NumberSelectorConfig(min=10, max=80, step=5, unit_of_measurement="%", mode=selector.NumberSelectorMode.SLIDER)
        ),
    })


# ---------------------------------------------------------------------------
# Invoer verwerking
# ---------------------------------------------------------------------------

def _process_collected(data: dict) -> dict:
    """
    Verwerkt het gecombineerde data-dict na alle stappen.
    NumberSelector levert float -- integers worden expliciet omgezet.
    """
    processed = data.copy()
    processed["battery_modules"] = int(float(data.get("battery_modules", 1)))
    processed["update_interval"] = int(float(data.get("update_interval", 5)))
    processed["min_soc"] = float(data.get("min_soc", 10.0))
    processed["system_cost_euro"] = float(data.get("system_cost_euro", 15000.0))
    processed["fixed_price_eur"] = float(data.get("fixed_price_eur", 0.25))
    processed["feed_in_mode"] = data.get("feed_in_mode", FEED_IN_MODE_FIXED)
    processed["feed_in_tariff_eur"] = float(data.get("feed_in_tariff_eur", FEED_IN_TARIFF_DEFAULT_EUR))

    # Tijdsblokken valideren
    raw_blocks = str(data.get("fixed_time_blocks", "")).strip()
    if raw_blocks:
        try:
            blocks = _json.loads(raw_blocks)
            if not isinstance(blocks, list):
                raise ValueError
            for b in blocks:
                if len(b) != 3 or not isinstance(b[2], str):
                    raise ValueError
            processed["fixed_time_blocks"] = blocks
        except Exception:
            processed["fixed_time_blocks"] = ""
    else:
        processed["fixed_time_blocks"] = ""

    # Zorg dat alle optionele velden altijd aanwezig zijn
    processed["ev_min_soc"] = float(data.get("ev_min_soc", EV_MIN_SOC_DEFAULT))
    processed.setdefault("ev_charging_sensor", "")
    processed.setdefault("price_sensor", "")
    processed.setdefault("zonneplan_sensor", "")
    processed.setdefault("feed_in_tariff_sensor", "")
    processed.setdefault("solar_forecast_sensor", "")
    processed.setdefault("pv_present", False)

    processed.pop("reset_profile_on_save", None)
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
            description_placeholders={"info": "Wijs de P1-sensoren aan van je slimme meter, één import én export per fase."},
        )

    async def async_step_hardware(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_contract()
        return self.async_show_form(
            step_id="hardware",
            data_schema=_schema_hardware(self._data),
            description_placeholders={"info": "Kies de hardware die jouw installatie het best beschrijft."},
        )

    async def async_step_contract(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_pricing()
        return self.async_show_form(
            step_id="contract",
            data_schema=_schema_contract(self._data),
            description_placeholders={"info": "Dynamisch = Zonneplan uurprijzen. Vast = tijdsblokken (nacht/dag/piek)."},
        )

    async def async_step_pricing(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_feed_in()
        contract = self._data.get("contract_type", CONTRACT_DYNAMIC)
        if contract == CONTRACT_FIXED:
            return self.async_show_form(
                step_id="pricing",
                data_schema=_schema_pricing_fixed(self._data),
                description_placeholders={"info": "Vul je vaste kWh-prijs in. Tijdsblokken leeg laten = standaard nacht/dag/avondpiek."},
            )
        return self.async_show_form(
            step_id="pricing",
            data_schema=_schema_pricing_dynamic(self._data),
            description_placeholders={"info": "Wijs je prijssensor aan. Zonneplan (optioneel) geeft uurprijzen voor 48 uur vooruit."},
        )

    async def async_step_feed_in(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_feed_in_detail()
        return self.async_show_form(
            step_id="feed_in",
            data_schema=_schema_feed_in_mode(self._data),
            description_placeholders={"info": "Terugleveringstarief voor PV-overschot dat de batterij niet opvangt."},
        )

    async def async_step_feed_in_detail(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_pv_choice()
        mode = self._data.get("feed_in_mode", FEED_IN_MODE_FIXED)
        if mode == FEED_IN_MODE_SENSOR:
            return self.async_show_form(
                step_id="feed_in_detail",
                data_schema=_schema_feed_in_sensor(self._data),
                description_placeholders={"info": "Wijs de sensor aan die het huidige terugleveringstarief levert."},
            )
        return self.async_show_form(
            step_id="feed_in_detail",
            data_schema=_schema_feed_in_fixed(self._data),
            description_placeholders={"info": "Vul het vaste terugleveringstarief in euro per kWh in."},
        )

    async def async_step_pv_choice(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            if user_input.get("pv_present", False):
                return await self.async_step_pv_sensor()
            self._data["solar_forecast_sensor"] = ""
            return await self.async_step_ev()
        return self.async_show_form(
            step_id="pv_choice",
            data_schema=_schema_pv_choice(self._data),
            description_placeholders={"info": "Heb je zonnepanelen? De optimizer gebruikt de verwachte dagproductie in zijn planning."},
        )

    async def async_step_pv_sensor(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_ev()
        return self.async_show_form(
            step_id="pv_sensor",
            data_schema=_schema_pv_sensor(self._data),
            description_placeholders={"info": "Wijs de forecast.solar sensor aan met de verwachte dagproductie in kWh."},
        )

    async def async_step_ev(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return self._create_entry()
        return self.async_show_form(
            step_id="ev",
            data_schema=_schema_ev(self._data),
            description_placeholders={"info": "Optioneel: wijs een binary sensor aan die aangeeft wanneer je EV laadt. De batterij houdt dan een minimale reserve aan."},
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
                "opt_sensors":  "🔌  P1 sensoren & temperatuur",
                "opt_hardware": "⚙️  Hardware & instellingen",
                "opt_contract": "💶  Contracttype & prijzen",
                "opt_feed_in":  "🔋  Terugleveringstarief",
                "opt_pv":       "☀️  Zonnepanelen & forecast",
                "opt_ev":       "🚗  EV-laden reserve",
                "opt_reset":    "🔄  Reset leerprofiel",
            },
        )

    # ------------------------------------------------------------------
    # Sectie: P1 sensoren
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
    # Sectie: Hardware & instellingen
    # ------------------------------------------------------------------

    async def async_step_opt_hardware(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self._save()
        return self.async_show_form(
            step_id="opt_hardware",
            data_schema=_schema_hardware(self._data),
            description_placeholders={"info": "Wijzig het batterij- of omvormermodel, SoC-grens of update-interval."},
        )

    # ------------------------------------------------------------------
    # Sectie: Contract & prijzen (twee substappen)
    # ------------------------------------------------------------------

    async def async_step_opt_contract(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_opt_pricing()
        return self.async_show_form(
            step_id="opt_contract",
            data_schema=_schema_contract(self._data),
            description_placeholders={"info": "Dynamisch = Zonneplan uurprijzen. Vast = tijdsblokken (nacht/dag/piek)."},
        )

    async def async_step_opt_pricing(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self._save()
        contract = self._data.get("contract_type", CONTRACT_DYNAMIC)
        if contract == CONTRACT_FIXED:
            return self.async_show_form(
                step_id="opt_pricing",
                data_schema=_schema_pricing_fixed(self._data),
                description_placeholders={"info": "Vul je vaste kWh-prijs in. Tijdsblokken leeg = standaard nacht/dag/avondpiek."},
            )
        return self.async_show_form(
            step_id="opt_pricing",
            data_schema=_schema_pricing_dynamic(self._data),
            description_placeholders={"info": "Wijs je prijssensor aan. Zonneplan (optioneel) geeft uurprijzen voor 48 uur vooruit."},
        )

    # ------------------------------------------------------------------
    # Sectie: Terugleveringstarief (twee substappen)
    # ------------------------------------------------------------------

    async def async_step_opt_feed_in(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_opt_feed_in_detail()
        return self.async_show_form(
            step_id="opt_feed_in",
            data_schema=_schema_feed_in_mode(self._data),
            description_placeholders={"info": "Terugleveringstarief voor PV-overschot dat de batterij niet opvangt."},
        )

    async def async_step_opt_feed_in_detail(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self._save()
        mode = self._data.get("feed_in_mode", FEED_IN_MODE_FIXED)
        if mode == FEED_IN_MODE_SENSOR:
            return self.async_show_form(
                step_id="opt_feed_in_detail",
                data_schema=_schema_feed_in_sensor(self._data),
                description_placeholders={"info": "Wijs de sensor aan die het huidige terugleveringstarief levert."},
            )
        return self.async_show_form(
            step_id="opt_feed_in_detail",
            data_schema=_schema_feed_in_fixed(self._data),
            description_placeholders={"info": "Vul het vaste terugleveringstarief in euro per kWh in."},
        )

    # ------------------------------------------------------------------
    # Sectie: PV & forecast (twee substappen)
    # ------------------------------------------------------------------

    async def async_step_opt_pv(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            if user_input.get("pv_present", False):
                return await self.async_step_opt_pv_sensor()
            self._data["solar_forecast_sensor"] = ""
            return await self._save()
        return self.async_show_form(
            step_id="opt_pv",
            data_schema=_schema_pv_choice(self._data),
            description_placeholders={"info": "Schakel PV in of uit. Bij uitschakelen wordt de forecast sensor gewist."},
        )

    async def async_step_opt_pv_sensor(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self._save()
        return self.async_show_form(
            step_id="opt_pv_sensor",
            data_schema=_schema_pv_sensor(self._data),
            description_placeholders={"info": "Wijs de forecast.solar sensor aan met de verwachte dagproductie in kWh."},
        )

    # ------------------------------------------------------------------
    # Sectie: EV-laden reserve
    # ------------------------------------------------------------------

    async def async_step_opt_ev(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self._save()
        return self.async_show_form(
            step_id="opt_ev",
            data_schema=_schema_ev(self._data),
            description_placeholders={"info": "Wijs de binary sensor aan die aangeeft wanneer je EV laadt. De batterij houdt dan de ingestelde minimale reserve aan."},
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
                    "batterijgezondheid blijven bewaard. De integratie valt "
                    "terug op Smart Dynamic totdat er nieuwe profieldata is."
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
