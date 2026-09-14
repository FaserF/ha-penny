"""PENNY – Home Assistant Custom Component."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant import config_entries, core
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import DOMAIN, PLATFORMS
from .coordinator import PennyDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: core.HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the PENNY integration (config-entry only)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Set up PENNY eBons from a config entry."""
    _LOGGER.debug(
        "Setting up PENNY entry %s (reweId: %s)",
        entry.entry_id,
        entry.data.get("rewe_id"),
    )
    hass.data.setdefault(DOMAIN, {})

    coordinator = PennyDataUpdateCoordinator(hass, entry)
    await coordinator.async_load_cache()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    try:
        await coordinator.async_config_entry_first_refresh()
    except UpdateFailed as err:
        if not coordinator.data:
            raise ConfigEntryNotReady(
                f"Cannot connect to PENNY API for reweId {coordinator.rewe_id}: {err}"
            ) from err
        _LOGGER.warning(
            "Initial PENNY update failed for reweId %s, using cached data. Error: %s",
            coordinator.rewe_id,
            err,
        )

    entry.async_on_unload(entry.add_update_listener(_async_update_options))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.debug("PENNY entry %s set up successfully", entry.entry_id)
    return True


async def _async_update_options(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
) -> None:
    """Reload the entry when options change."""
    _LOGGER.debug("Reloading PENNY entry %s due to option updates", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(
    hass: core.HomeAssistant, config_entry: config_entries.ConfigEntry
) -> bool:
    """Migrate old entry."""
    _LOGGER.debug("Migrating PENNY config entry from version %s", config_entry.version)
    return True


async def async_unload_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading PENNY entry %s", entry.entry_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
