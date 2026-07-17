"""BatteryLabs 3-Phase — integratie setup."""
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)

from .const import DOMAIN
from .sensor import BatteryCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "select", "button", "number"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    # Coordinator hier aanmaken — vóór de platforms — zodat select/number/button
    # de coordinator gegarandeerd in hass.data vinden (geen setup-race meer).
    # Opties overschrijven de oorspronkelijke config-data.
    merged_config = {**entry.data, **entry.options}
    coordinator = BatteryCoordinator(hass, merged_config, entry.entry_id)
    await coordinator.async_load_data()
    await coordinator.async_load_profile()

    # Snelle cyclus: abonneer op P1 state changes.
    p1_sensors = [
        merged_config.get(k, "")
        for k in ("l1_import_kw", "l1_export_kw",
                  "l2_import_kw", "l2_export_kw",
                  "l3_import_kw", "l3_export_kw")
        if merged_config.get(k, "")
    ]
    cancel_p1 = async_track_state_change_event(
        hass, p1_sensors, coordinator.handle_p1_update
    )

    # Trage cyclus: profiel, score engine, plan, PV forecast (60 seconden).
    cancel_slow = async_track_time_interval(
        hass, coordinator.update_slow, timedelta(seconds=60)
    )
    coordinator.set_cancel_timer(cancel_p1, cancel_slow)

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Herlaad de integratie automatisch wanneer opties wijzigen.
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id, None)
        if coordinator is not None:
            coordinator.cancel()
    return unload_ok
