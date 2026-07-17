"""Button entiteit voor BatteryLabs 3-Phase — reset leerprofiel."""
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([ProfileResetButton(config_entry)])


class ProfileResetButton(ButtonEntity):
    """
    Knop die het leerprofielbestand wist en de voortgang reset naar 0%.
    Financiële tellers, SoH en alle andere state blijven intact.
    """

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry_id = config_entry.entry_id
        self._attr_name = "BatteryLabs Reset Leerprofiel"
        self._attr_unique_id = f"bl_reset_profile_{config_entry.entry_id}"
        self._attr_icon = "mdi:brain"

    async def async_press(self) -> None:
        """
        Verwijder het profielbestand en stel de coordinator in op reset.
        De coordinator detecteert bij de volgende update dat het profiel
        ontbreekt en herstart het leerproces automatisch.
        """
        coordinator = self.hass.data[DOMAIN].get(self._entry_id)
        if coordinator is not None:
            await coordinator.async_reset_profile()
            _LOGGER.info("BatteryLabs: leerprofiel gereset via knop")
        else:
            _LOGGER.warning("BatteryLabs: coordinator niet gevonden bij reset")

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": "BatteryLabs Systeem",
            "manufacturer": "BatteryLabs",
            "model": "Smart 3-Phase Simulator",
            "sw_version": "4.0.0",
        }
