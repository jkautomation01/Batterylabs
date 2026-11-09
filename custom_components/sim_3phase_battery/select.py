from homeassistant.components.select import SelectEntity
from .const import DOMAIN, ALL_MODES, MODE_AUTO

async def async_setup_entry(hass, config_entry, async_add_entities):
    async_add_entities([BatteryModeSelect(config_entry)])

class BatteryModeSelect(SelectEntity):
    def __init__(self, config_entry):
        self._entry_id = config_entry.entry_id
        self._attr_name = "BatteryLabs Strategie"
        self._attr_unique_id = f"{config_entry.entry_id}_mode"
        self._attr_options = ALL_MODES
        self._attr_current_option = MODE_AUTO

    async def async_added_to_hass(self) -> None:
        # Herstel de actieve modus uit de coordinator (die mode naar schijf
        # persisteert), zodat de dropdown na een herstart de werkelijke
        # strategie toont in plaats van terug te vallen op Smart.
        coordinator = self.hass.data.get(DOMAIN, {}).get(self._entry_id)
        if coordinator is not None:
            mode = coordinator.data.get("mode")
            if mode in self._attr_options:
                self._attr_current_option = mode
                self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        self.hass.bus.async_fire("sim_battery_mode_changed", {"mode": option})
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
