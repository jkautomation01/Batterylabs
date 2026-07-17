"""Number entiteiten voor BatteryLabs 3-Phase — instelbare drempelwaarden."""
import logging
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PEAK_SHAVING_THRESHOLD_DEFAULT = 2200.0   # W per fase
PEAK_SHAVING_MIN_SOC_DEFAULT   = 15.0    # %
CYCLE_BUDGET_PER_DAY_DEFAULT   = 1.5     # volledige cycli per dag


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN].get(config_entry.entry_id)
    async_add_entities([
        PeakShavingThresholdNumber(hass, config_entry, coordinator),
        PeakShavingMinSocNumber(hass, config_entry, coordinator),
        CycleBudgetPerDayNumber(hass, config_entry, coordinator),
    ])


class _PersistentNumber(NumberEntity):
    """
    Basis klasse voor persistente number entiteiten.
    Slaat de waarde op in de coordinator zodat hij herstart overleeft.
    """

    def __init__(self, hass, config_entry, coordinator, data_key, default):
        self._hass = hass
        self._entry_id = config_entry.entry_id
        self._coordinator = coordinator
        self._data_key = data_key
        self._default = default
        # Laad opgeslagen waarde of gebruik default
        if coordinator is not None:
            self._value = float(coordinator.data.get(data_key, default))
        else:
            self._value = default

    @property
    def native_value(self) -> float:
        if self._coordinator:
            return float(self._coordinator.data.get(self._data_key, self._default))
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        self._value = value
        if self._coordinator:
            self._coordinator.data[self._data_key] = value
            # Direct opslaan zodat herstart de waarde behoudt
            await self._coordinator.async_save_state()
        self.async_write_ha_state()

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": "BatteryLabs Systeem",
            "manufacturer": "BatteryLabs",
            "model": "Smart 3-Phase Simulator",
            "sw_version": "4.0.0",
        }


class PeakShavingThresholdNumber(_PersistentNumber):
    """Instelbare peak shaving drempel per fase in Watt."""

    def __init__(self, hass, config_entry, coordinator):
        super().__init__(
            hass, config_entry, coordinator,
            data_key="peak_shaving_threshold_w",
            default=PEAK_SHAVING_THRESHOLD_DEFAULT,
        )
        self._attr_name = "BatteryLabs Peak Shaving Drempel"
        self._attr_unique_id = f"bl_ps_threshold_{config_entry.entry_id}"
        self._attr_icon = "mdi:lightning-bolt-circle"
        self._attr_native_min_value = 500.0
        self._attr_native_max_value = 7000.0
        self._attr_native_step = 100.0
        self._attr_native_unit_of_measurement = "W"
        self._attr_mode = NumberMode.BOX

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "omschrijving": (
                "De batterij houdt netimport per fase onder deze waarde. "
                "Alles boven dit vermogen wordt van het net betrokken."
            ),
            "default_w": PEAK_SHAVING_THRESHOLD_DEFAULT,
        }


class PeakShavingMinSocNumber(_PersistentNumber):
    """Minimum SoC voor peak shaving — batterij ontlaadt niet verder."""

    def __init__(self, hass, config_entry, coordinator):
        super().__init__(
            hass, config_entry, coordinator,
            data_key="peak_shaving_min_soc",
            default=PEAK_SHAVING_MIN_SOC_DEFAULT,
        )
        self._attr_name = "BatteryLabs Peak Shaving Min SoC"
        self._attr_unique_id = f"bl_ps_min_soc_{config_entry.entry_id}"
        self._attr_icon = "mdi:battery-alert"
        self._attr_native_min_value = 5.0
        self._attr_native_max_value = 50.0
        self._attr_native_step = 1.0
        self._attr_native_unit_of_measurement = "%"
        self._attr_mode = NumberMode.SLIDER

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "omschrijving": (
                "Peak shaving stopt als de SoC deze waarde bereikt. "
                "Zo blijft er altijd een noodreserve over."
            ),
            "default_pct": PEAK_SHAVING_MIN_SOC_DEFAULT,
        }


class CycleBudgetPerDayNumber(_PersistentNumber):
    """Maximaal aantal volledige laad/ontlaadcycli per dag voor de DP-optimizer."""

    def __init__(self, hass, config_entry, coordinator):
        super().__init__(
            hass, config_entry, coordinator,
            data_key="cycle_budget_per_day",
            default=CYCLE_BUDGET_PER_DAY_DEFAULT,
        )
        self._attr_name = "BatteryLabs Cyclusbudget per Dag"
        self._attr_unique_id = f"bl_cycle_budget_{config_entry.entry_id}"
        self._attr_icon = "mdi:battery-sync"
        self._attr_native_min_value = 0.2
        self._attr_native_max_value = 3.0
        self._attr_native_step = 0.1
        self._attr_native_unit_of_measurement = "cycli/dag"
        self._attr_mode = NumberMode.SLIDER

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "omschrijving": (
                "Hoeveel volledige laad/ontlaadcycli de DP-optimizer maximaal "
                "mag maken per dag. Lager = conservatiever, hoger = agressiever. "
                "Werkt alleen als de DP-optimizer actief is."
            ),
            "default_cycli_per_dag": CYCLE_BUDGET_PER_DAY_DEFAULT,
        }
