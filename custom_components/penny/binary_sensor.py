"""PENNY binary sensor platform."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import ATTR_ATTRIBUTION
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .coordinator import PennyDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up PENNY binary sensors from a config entry."""
    coordinator: PennyDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    if coordinator.is_authenticated:
        async_add_entities(
            [PennyEbonSubscriptionSensor(coordinator)],
            update_before_add=False,
        )


class PennyEbonSubscriptionSensor(
    CoordinatorEntity[PennyDataUpdateCoordinator], BinarySensorEntity
):
    """eBon opt-in subscription status (True = subscribed)."""

    _attr_icon = "mdi:email-check"
    _attr_has_entity_name = True
    _attr_name = "eBon Subscription"

    def __init__(self, coordinator: PennyDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"penny_{coordinator.rewe_id}_ebon_subscription"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.rewe_id)},
            name=coordinator.config_entry.title,
            manufacturer="PENNY",
            model="eBon Account",
            configuration_url=coordinator.configuration_url,
        )

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.data:
            return None
        subscription = self.coordinator.data.get("subscription")
        if subscription is None:
            return None
        if isinstance(subscription, bool):
            return subscription
        if isinstance(subscription, dict):
            if not subscription:
                return None
            for key in ("isSubscribed", "subscribed", "active", "status", "optIn"):
                if key in subscription:
                    val = subscription[key]
                    if isinstance(val, bool):
                        return val
                    if isinstance(val, str):
                        return val.lower() in ("true", "active", "subscribed", "yes", "1")
        if isinstance(subscription, list):
            return len(subscription) > 0
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        subscription = (self.coordinator.data or {}).get("subscription")
        attrs: dict[str, Any] = {ATTR_ATTRIBUTION: ATTRIBUTION}
        if isinstance(subscription, dict):
            attrs.update(subscription)
        return attrs

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success or self.coordinator.is_data_valid
        ) and self.coordinator.data is not None
