"""PENNY button platform."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import PennyDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up PENNY button from a config entry."""
    coordinator: PennyDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    if coordinator.is_authenticated:
        async_add_entities([PennyForceUpdateButton(coordinator)], update_before_add=False)


class PennyForceUpdateButton(ButtonEntity):
    """Button to force-refresh PENNY eBon data."""

    _attr_icon = "mdi:refresh"
    _attr_has_entity_name = True
    _attr_name = "Force Update"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: PennyDataUpdateCoordinator) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"penny_{coordinator.rewe_id}_force_update"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.rewe_id)},
            name=coordinator.config_entry.title,
            manufacturer="PENNY",
            model="eBon Account",
            configuration_url=coordinator.configuration_url,
        )

    async def async_press(self) -> None:
        """Trigger a forced refresh."""
        _LOGGER.info(
            "Force update pressed for PENNY reweId=%s", self.coordinator.rewe_id
        )
        self.coordinator._force_update = True
        await self.coordinator.async_request_refresh()
